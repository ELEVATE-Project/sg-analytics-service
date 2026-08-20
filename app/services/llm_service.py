import asyncio
import json
import logging
import re
import time
from typing import Optional

from google import genai
from sqlalchemy import text

from ..core.config import settings
from ..api.schemas import ValidationResponse
from ..database.postgres import async_session

logger = logging.getLogger(__name__)

if settings.GEMINI_API_KEY:
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
else:
    genai_client = None

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
    if not genai_client:
        logger.error(
            "[validate_pairs_with_llm] GEMINI_API_KEY is not configured "
            "— rejecting all %s pairs (fail-closed).",
            len(pairs_data),
        )
        return {}

    try:
        # Prompt fetch + formatting are both inside the exception boundary so
        # any failure (DB down, template error) returns {} cleanly.
        system_prompt_text, user_prompt_template = await get_prompt()

        user_prompt_text = user_prompt_template.replace(
            "{{pairs_data}}", json.dumps(pairs_data, indent=2)
        )
        prompt = f"{system_prompt_text}\n\n{user_prompt_text}"

        # Run blocking Gemini I/O in a worker thread to keep the event loop free.
        response = await asyncio.to_thread(
            genai_client.models.generate_content,
            model="gemini-flash-lite-latest",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ValidationResponse,
                temperature=0.0,
            ),
        )

        # Log token usage for every completed call, even when metadata is absent.
        usage = getattr(response, "usage_metadata", None)
        logger.info(
            "[validate_pairs_with_llm] token usage — prompt=%s output=%s total=%s",
            getattr(usage, "prompt_token_count", "?") if usage else "?",
            getattr(usage, "candidates_token_count", "?") if usage else "?",
            getattr(usage, "total_token_count", "?") if usage else "?",
        )

        valid_ranks = {p["rank"] for p in pairs_data}

        validated = ValidationResponse.model_validate_json(response.text)
        judgements = validated.judgements

        passed = {}
        for j in judgements:
            if j.rank not in valid_ranks:
                logger.warning(
                    "[validate_pairs_with_llm] model returned out-of-range rank=%s — skipping.",
                    j.rank,
                )
                continue

            # All PASS criteria must hold (score threshold is MIN_LLM_SCORE=3;
            # see config for rationale on why 3 is chosen over 4).
            if (
                j.verdict == "PASS"
                and j.score >= settings.MIN_LLM_SCORE
                and not j.pii_detected
                and j.best_sol_id
                and has_action_verb(j.reason)
            ):
                passed[j.rank] = j.best_sol_id

        logger.info("[validate_pairs_with_llm] %s/%s pairs passed.", len(passed), len(pairs_data))
        for j in judgements:
            if j.rank not in passed:
                pii_note = " [PII]" if j.pii_detected else ""
                no_verb_note = " [NO_ACTION_VERB]" if not has_action_verb(j.reason) else ""
                logger.debug(
                    "  REJECTED rank=%s score=%s%s%s reason=%s",
                    j.rank, j.score, pii_note, no_verb_note, j.reason,
                )
        return passed

    except Exception as e:
        logger.error(
            "[validate_pairs_with_llm] LLM validation failed — rejecting all %s pairs (fail-closed): %r",
            len(pairs_data), e,
        )
        return {}
