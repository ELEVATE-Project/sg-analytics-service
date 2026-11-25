import asyncio
import json
import logging
import re
import time
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import text

from ..core.config import settings
from ..api.schemas import ValidationResponse
from ..database.postgres import async_session

logger = logging.getLogger(__name__)

if settings.OPENROUTER_API_KEY:
    openai_client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )
else:
    openai_client = None

# ---------------------------------------------------------------------------
# Prompt cache with TTL + version-change invalidation.
#
# cached_prompt      — (system_prompt, user_prompt) tuple
# prompt_fetched_at  — monotonic timestamp of last successful fetch
# prompt_version_id  — DB id of the cached row; used to detect activation
#                       of a new prompt_version without waiting for TTL expiry
# ---------------------------------------------------------------------------
cached_prompt: Optional[tuple[str, str]] = None
prompt_fetched_at: float = 0.0
prompt_version_id: Optional[str] = None


async def fetch_active_prompt() -> tuple[str, str, str]:
    """Fetch the active system and user prompt rows from Postgres.

    Returns (system_prompt, user_prompt, version_id).
    """
    async with async_session() as session:
        result = await session.execute(text(
            "SELECT id, system_prompt, user_prompt FROM prompt_version"
            " WHERE is_active = true ORDER BY created_at DESC LIMIT 1"
        ))
        row = result.fetchone()
        if not row:
            raise ValueError("No active prompt found in database")
        return row.system_prompt, row.user_prompt, str(row.id)


async def get_prompt() -> tuple[str, str]:
    """Return cached prompt, refreshing when TTL expires or version changes."""
    global cached_prompt, prompt_fetched_at, prompt_version_id

    now = time.monotonic()
    ttl_expired = (now - prompt_fetched_at) >= settings.PROMPT_TTL_SECONDS

    if cached_prompt is not None and not ttl_expired:
        return cached_prompt

    system_prompt, user_prompt, version_id = await fetch_active_prompt()

    if version_id != prompt_version_id:
        logger.info(
            "[llm_service] Active prompt refreshed: version %s → %s",
            prompt_version_id, version_id,
        )

    cached_prompt = (system_prompt, user_prompt)
    prompt_fetched_at = now
    prompt_version_id = version_id
    return cached_prompt


# ---------------------------------------------------------------------------
# Action-verb guard
#
# The system prompt explicitly requires a solution to describe "an action that
# was TAKEN or PROPOSED" and lists canonical verbs. We enforce that at least
# one of those verbs (or common synonyms) appears in the LLM's `reason` text
# so that the filter does not rely solely on the model honouring its own
# instructions.
# ---------------------------------------------------------------------------
ACTION_VERB_RE = re.compile(
    r"\b("
    r"arrang|work|talk|organiz|organis|explain|motivat|ensur|"
    r"help|made|mak|conduct|implement|establish|creat|initiat|launch|"
    r"start|complet|provid|support|facilitat|coordinat|connect|"
    r"built|build|form|train|educat|rais|collect|distribut|submit|"
    r"resolv|address|identif|took|tak|carr|set\s+up|"
    r"action|counsel|stop|persuad|secur|advis"
    r")[a-z]*\b",
    re.IGNORECASE,
)


def has_action_verb(reason: str) -> bool:
    """Return True if `reason` contains at least one recognised action verb."""
    return bool(ACTION_VERB_RE.search(reason or ""))


async def validate_pairs_with_llm(pairs_data: list[dict]) -> dict[int, str]:
    """
    Validate challenge-solution pairs using the Gemini LLM.

    pairs_data: list of {"rank": int, "challenge_text": str, "solutions": [{"sol_id": str, "text": str}]}
    Returns: dict mapping `rank` to the `best_sol_id` of the chosen solution.
    """
    if not openai_client:
        logger.error(
            "[validate_pairs_with_llm] OPENROUTER_API_KEY is not configured "
            "— rejecting all %s pairs (fail-closed).",
            len(pairs_data),
        )
        return {}

    try:
        system_prompt_text, user_prompt_template = await get_prompt()

        passed = {}
        batch_size = 10
        
        for i in range(0, len(pairs_data), batch_size):
            batch = pairs_data[i:i + batch_size]

            # Remap rank to 0..len(batch)-1 so the model always receives consistent local ranks
            batch_payload = []
            local_to_global = {}
            for local_idx, item in enumerate(batch):
                global_rank = item["rank"]
                local_to_global[local_idx] = global_rank
                local_to_global[local_idx + 1] = global_rank  # Support 1-based indexing from LLM as well
                local_to_global[global_rank] = global_rank    # Support global rank if echoed directly

                item_copy = dict(item)
                item_copy["rank"] = local_idx
                batch_payload.append(item_copy)
            
            payload_json = json.dumps(batch_payload, indent=2, ensure_ascii=False)
            user_prompt_text = user_prompt_template
            if "{{pairs_data}}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace("{{pairs_data}}", payload_json)
            elif "{pairs_data}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace("{pairs_data}", payload_json)
            elif "{{pairs}}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace("{{pairs}}", payload_json)
            elif "{pairs}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace("{pairs}", payload_json)
            elif "{{data}}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace("{{data}}", payload_json)
            elif "{data}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace("{data}", payload_json)
            else:
                user_prompt_text = f"{user_prompt_text}\n\nData:\n{payload_json}"

            logger.info(
                "[validate_pairs_with_llm] dispatching batch %d-%d with %d items. Sample prompt: %s",
                i, i + len(batch), len(batch_payload), user_prompt_text[:300].replace("\n", " "),
            )

            try:
                response = await openai_client.beta.chat.completions.parse(
                    model=settings.OPENROUTER_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt_text},
                        {"role": "user", "content": user_prompt_text},
                    ],
                    response_format=ValidationResponse,
                    temperature=settings.LLM_TEMPERATURE,
                    max_completion_tokens=settings.LLM_MAX_TOKENS,
                )

                usage = response.usage
                logger.info(
                    "[validate_pairs_with_llm] batch %d-%d token usage — prompt=%s output=%s total=%s",
                    i, i + len(batch),
                    getattr(usage, "prompt_tokens", "?") if usage else "?",
                    getattr(usage, "completion_tokens", "?") if usage else "?",
                    getattr(usage, "total_tokens", "?") if usage else "?",
                )

                validated = response.choices[0].message.parsed
                if not validated:
                    logger.error("[validate_pairs_with_llm] LLM failed to parse response for batch.")
                    continue
                    
                judgements = validated.judgements

                for j in judgements:
                    if j.rank not in local_to_global:
                        logger.warning(
                            "[validate_pairs_with_llm] model returned out-of-range rank=%s — skipping.",
                            j.rank,
                        )
                        continue

                    global_rank = local_to_global[j.rank]

                    if (
                        j.verdict == "PASS"
                        and j.score >= settings.MIN_LLM_SCORE
                        and not j.pii_detected
                        and j.best_sol_id
                        and has_action_verb(j.reason)
                    ):
                        passed[global_rank] = j.best_sol_id
                    else:
                        pii_note = " [PII]" if j.pii_detected else ""
                        no_verb_note = " [NO_ACTION_VERB]" if not has_action_verb(j.reason) else ""
                        logger.info(
                            "  [LLM JUDGEMENT] rank=%s (global=%s) verdict=%s score=%s%s%s reason=%s",
                            j.rank, global_rank, j.verdict, j.score, pii_note, no_verb_note, j.reason,
                        )
            except Exception as e:
                logger.error("[validate_pairs_with_llm] Batch failed: %r", e)

        logger.info("[validate_pairs_with_llm] %s/%s pairs passed overall.", len(passed), len(pairs_data))
        return passed

    except Exception as e:
        logger.error(
            "[validate_pairs_with_llm] LLM validation failed — rejecting all %s pairs (fail-closed): %r",
            len(pairs_data), e,
        )
        return {}
