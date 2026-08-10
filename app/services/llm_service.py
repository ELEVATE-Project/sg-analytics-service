import json
import logging
from google import genai
from ..config import settings
from ..api.models.schemas import ValidationResponse

logger = logging.getLogger(__name__)

if settings.GEMINI_API_KEY:
    genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
else:
    genai_client = None

def validate_pairs_with_llm(pairs_data: list[dict]) -> dict[int, str]:
    """
    pairs_data: list of {"rank": int, "challenge_text": str, "solutions": [{"sol_id": str, "text": str}]}
    Returns: dict mapping `rank` to the `best_sol_id` of the chosen solution.
    """
    if not genai_client:
        logger.warning(
            "[validate_pairs_with_llm] genai_client is None (no GEMINI_API_KEY) "
            "— skipping LLM validation, passing top candidate for all."
        )
        return {p["rank"]: p["solutions"][0]["sol_id"] for p in pairs_data if p.get("solutions")}

    prompt = (
        "You are a strict, skeptical evaluator of challenge-solution pairs for a public knowledge base. "
        "You will receive a list of items. Each item has a challenge and a list of candidate solutions.\n"
        "For each challenge, evaluate the candidate solutions and pick the BEST ONE that actually solves the challenge's specific problem.\n\n"
        
        "A valid solution must pass ALL of these criteria:\n"
        "1. MATCH: Solution must address the challenge's SPECIFIC root cause, not just the same broad "
        "topic (e.g. a 'poverty' solution does NOT answer an 'Aadhaar card' challenge, even though both "
        "are education issues).\n"
        "2. SPECIFICITY: Solution must describe a concrete action with real detail — reject "
        "generic/templated text that could paste onto almost any education challenge unchanged.\n"
        "3. COHERENCE: Text must be logical and free of contradictions or nonsensical content.\n"
        "4. GRAMMAR: Minor grammar or translation roughness is fine. Only FAIL on grammar if more than "
        "~10% of the text is broken, garbled, or unreadable.\n"
        "5. PII: If the text names a specific PERSON, a specific VILLAGE/hamlet name, a street address, "
        "or a phone number, this is an automatic FAIL. District and state names are NOT PII and are fine.\n"
        "6. VALID STATEMENT: Reject (FAIL) if the text is just a question.\n"
        "7. ACTION REQUIRED: The solution MUST describe an action that was TAKEN or PROPOSED — something "
        "someone actually DID or is DOING (e.g. 'We talked to the parents', 'I worked with the principal "
        "to get Aadhaar cards made', 'A meeting was organized'). REJECT any candidate that merely "
        "describes the problem, a state-of-affairs, or a rule — even if it is on the correct topic "
        "(e.g. 'Children without Aadhaar cards are not admitted to school' is a PROBLEM STATEMENT, not "
        "a solution — FAIL it). Look for active verbs: arranged, worked, talked, organized, explained, "
        "motivated, ensured, helped, made, conducted.\n\n"

        "If multiple solutions pass, pick the one that is most detailed and actionable. "
        "Set `score` from 1 (no match) to 5 (excellent match) for the best candidate. "
        "PASS requires a valid candidate with score >= 3 AND pii_detected=false AND grammar "
        "acceptable AND valid statements AND an actual action described. Otherwise FAIL. "
        "If no solutions pass, best_sol_id should be null.\n\n"

        "Data:\n"
        f"{json.dumps(pairs_data, indent=2)}\n\n"

        "Return a `judgements` list, one entry per challenge, using the exact `rank` given. "
        "Include rank, best_sol_id (or null), pii_detected, verdict, and reason."
    )

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

        result = json.loads(response.text)
        judgements = result.get("judgements", [])
        
        passed = {}
        for j in judgements:
            if j.get("verdict") == "PASS" and j.get("score", 0) >= 3 and not j.get("pii_detected") and j.get("best_sol_id"):
                passed[j["rank"]] = j["best_sol_id"]
                
        logger.info("[validate_pairs_with_llm] %s/%s pairs passed.", len(passed), len(pairs_data))
        for j in judgements:
            if j["rank"] not in passed:
                pii_note = " [PII]" if j.get("pii_detected") else ""
                logger.debug(
                    "  REJECTED rank=%s score=%s%s reason=%s",
                    j['rank'], j.get('score'), pii_note, j.get('reason'),
                )
        return passed
    except Exception as e:
        logger.error("[validate_pairs_with_llm] LLM Validation ERROR - falling back to pass-all top: %r", e)
        return {p["rank"]: p["solutions"][0]["sol_id"] for p in pairs_data if p.get("solutions")}
