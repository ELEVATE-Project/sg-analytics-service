import json
import logging
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

# Module-level prompt cache — populated on first LLM call, reused thereafter.
_cached_prompt: Optional[tuple[str, str]] = None


async def _fetch_active_prompt() -> tuple[str, str]:
    """Fetch the active system and user prompt rows from Postgres."""
    async with async_session() as session:
        result = await session.execute(text(
            "SELECT system_prompt, user_prompt FROM prompt_version"
            " WHERE is_active = true ORDER BY created_at DESC LIMIT 1"
        ))
        row = result.fetchone()
        if not row:
            raise ValueError("No active prompt found in database")
        return row.system_prompt, row.user_prompt


async def _get_prompt() -> tuple[str, str]:
    """Return cached prompt tuple, or fetch from DB on first call."""
    global _cached_prompt
    if _cached_prompt is None:
        _cached_prompt = await _fetch_active_prompt()
    return _cached_prompt


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
        system_prompt_text, user_prompt_template = await _get_prompt()
    except Exception as e:
        logger.error("[validate_pairs_with_llm] Failed to fetch prompt from DB: %s", e)
        return {}

    user_prompt_text = user_prompt_template.replace(
        "{{pairs_data}}", json.dumps(pairs_data, indent=2)
    )
    prompt = f"{system_prompt_text}\n\n{user_prompt_text}"

    try:
        response = genai_client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ValidationResponse,
                temperature=0.0
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        if usage:
            logger.info(
                "[validate_pairs_with_llm] token usage — prompt=%s output=%s total=%s",
                getattr(usage, 'prompt_token_count', '?'),
                getattr(usage, 'candidates_token_count', '?'),
                getattr(usage, 'total_token_count', '?'),
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
            # Threshold matches seed.sql: score >= 3
            if j.verdict == "PASS" and j.score >= 3 and not j.pii_detected and j.best_sol_id:
                passed[j.rank] = j.best_sol_id

        logger.info("[validate_pairs_with_llm] %s/%s pairs passed.", len(passed), len(pairs_data))
        for j in judgements:
            if j.rank not in passed:
                pii_note = " [PII]" if j.pii_detected else ""
                logger.debug(
                    "  REJECTED rank=%s score=%s%s reason=%s",
                    j.rank, j.score, pii_note, j.reason,
                )
        return passed

    except Exception as e:
        logger.error(
            "[validate_pairs_with_llm] LLM validation failed — rejecting all %s pairs (fail-closed): %r",
            len(pairs_data), e,
        )
        return {}
