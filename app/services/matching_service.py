import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from ..core.config import settings
from ..cache import redis_cache
from .qdrant_service import fetch_top_challenges, fetch_top_solutions_async
from .llm_service import validate_pairs_with_llm

logger = logging.getLogger(__name__)

def payload_record_id(point):
    payload_id = (point.payload or {}).get("id")
    return str(point.id) if payload_id == 0 or payload_id is None else payload_id

def solution_debug_item(solution_point, mapped_solution_id=None):
    return {
        "point_id": str(solution_point.id),
        "id": payload_record_id(solution_point),
        "score": round(solution_point.score, 4),
        "mapped": solution_point.id == mapped_solution_id,
    }

def new_top_solutions_debug_log_file():
    settings.DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return settings.DEBUG_LOG_DIR / f"pre_llm_fetch_{timestamp}.jsonl"

def write_top_solution_debug_log(log_file: Path, debug_payload: dict):
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(debug_payload, ensure_ascii=False) + "\n")

def normalized_statement(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())

def top_scored_solutions(solutions, used_solutions: set, challenge_text: str, top_n: int = 5, min_score: float = None):
    if min_score is None:
        min_score = settings.MIN_MATCH_SCORE
    challenge_key = normalized_statement(challenge_text)
    candidates = []
    for solution in solutions:
        if str(solution.id) in used_solutions:
            continue
        # Enforce the score band to discard duplicates (score > MAX_MATCH_SCORE)
        # and ignore completely unrelated solutions (score < min_score).
        score = solution.score or 0.0
        if not (min_score <= score <= settings.MAX_MATCH_SCORE):
            continue
        payload = solution.payload or {}
        if normalized_statement(payload.get("statement")) == challenge_key:
            continue
        candidates.append(solution)

    candidates.sort(key=lambda s: s.score or 0.0, reverse=True)
    return candidates[:top_n]

def print_top_solution_debug(challenge_point, solutions, mapped_solution, log_file: Path):
    chal_payload = challenge_point.payload or {}
    mapped_solution_id = mapped_solution.id if mapped_solution else None
    debug_payload = {
        "challenge": {
            "point_id": str(challenge_point.id),
            "id": payload_record_id(challenge_point),
            "embedded_score": round(chal_payload.get("embedded_score", 0.0), 4),
        },
        "fetched_solution_count": len(solutions),
        "top_5_solutions": [
            solution_debug_item(solution, mapped_solution_id)
            for solution in solutions[:5]
        ],
        "mapped_solution": (
            solution_debug_item(mapped_solution, mapped_solution_id)
            if mapped_solution
            else None
        ),
    }
    write_top_solution_debug_log(log_file, debug_payload)
    mapped_id = debug_payload["mapped_solution"]["id"] if debug_payload["mapped_solution"] else None
    logger.debug(
        "[top_solutions_debug] challenge_id=%s top_5_logged=true mapped_solution_id=%s log_file=%s",
        debug_payload['challenge']['id'], mapped_id, log_file,
    )


# Maximum number of build-loop iterations before giving up.
# Prevents infinite looping when LLM rejection rate is high or data is scarce.
MAX_BUILD_ITERATIONS = 3

_qdrant_semaphore = asyncio.Semaphore(10)


async def _fetch_solutions_for_challenge(chal_point, used_solutions: set, used_threshold_override: float = None):
    """Fetch and filter solutions for a single challenge using the async Qdrant client.
    Returns (chal_point, top_sols, all_solutions) for debug logging."""
    async with _qdrant_semaphore:
        solutions = await fetch_top_solutions_async(chal_point.vector)
        used_threshold = settings.MIN_MATCH_SCORE

        # Fallback fetch if primary returned nothing
        if not solutions:
            solutions = await fetch_top_solutions_async(
                chal_point.vector,
                score_threshold=settings.FALLBACK_MATCH_SCORE,
            )
            used_threshold = settings.FALLBACK_MATCH_SCORE
            if solutions:
                logger.info(
                    "[fallback_fetch] challenge_id=%s primary=0 results, retried at threshold=%s -> got %s solutions",
                    (chal_point.payload or {}).get('id'), used_threshold, len(solutions),
                )

    chal_payload = chal_point.payload or {}
    top_sols = top_scored_solutions(
        solutions,
        used_solutions,
        chal_payload.get("statement", ""),
        top_n=settings.TOP_SOLUTIONS_PER_CHALLENGE,
        min_score=used_threshold,
    )
    return chal_point, top_sols, solutions


async def build_pairs(limit: int = settings.FINAL_RESULT_SIZE) -> list:
    validated_data = []

    # --- Load used sets from Redis ---
    used_challenges = await redis_cache.get_used_challenges()
    used_solutions  = await redis_cache.get_used_solutions()
    start_rank = len(used_challenges) + 1

    local_used_challenges = set(used_challenges)

    # Fetch enough challenges for one big batch
    # We want at least limit * 4 (e.g. 80 for 20 limit) to account for LLM rejections,
    # ensuring we only need 1 LLM call to get `limit` passing pairs.
    fetch_size = max(settings.PRE_LLM_FETCH_SIZE, limit * 4)
    challenges = fetch_top_challenges(local_used_challenges, limit=fetch_size)
    
    if not challenges:
        logger.info("[build_pairs] Exhausted challenges from DB. Stopping early.")
        return []

    debug_log_file = new_top_solutions_debug_log_file()
    logger.info("[pre_llm_fetch] single batch fetch of %s challenges. logs to %s", len(challenges), debug_log_file)

    # --- Fetch solutions for ALL challenges in parallel ---
    fetch_tasks = [
        _fetch_solutions_for_challenge(chal_point, used_solutions)
        for chal_point in challenges
    ]
    fetch_results = await asyncio.gather(*fetch_tasks)

    challenge_candidates = []
    llm_payload = []

    for chal_point, top_sols, all_solutions in fetch_results:
        best_sol_fallback = top_sols[0] if top_sols else None
        print_top_solution_debug(chal_point, all_solutions, best_sol_fallback, debug_log_file)

        if top_sols:
            rank = len(challenge_candidates)
            chal_payload = chal_point.payload or {}
            llm_payload.append({
                "rank": rank,
                "challenge_text": chal_payload.get("statement", ""),
                "solutions": [
                    {
                        "sol_id": str(s.id) if (s.payload or {}).get("id") in (0, None) else str((s.payload or {}).get("id")),
                        "text": (s.payload or {}).get("statement", "")
                    }
                    for s in top_sols
                ]
            })
            challenge_candidates.append({
                "challenge_point": chal_point,
                "top_solutions": top_sols
            })

    if not challenge_candidates:
        logger.info("[build_pairs] No challenge candidates found in this batch.")
        return []

    valid_results = await validate_pairs_with_llm(llm_payload)

    # If the LLM failed (e.g. 503 rate limit) it returns {}, so we exit early
    if not valid_results:
        logger.warning("[build_pairs] LLM validation returned empty (likely rate limit or error). Returning 0 results.")
        return []

    dropped_no_sol  = 0
    dropped_dedup   = 0
    dropped_limit   = 0

    accepted_challenge_ids = []
    accepted_solution_ids = []

    for rank, best_sol_id in valid_results.items():
        candidate_info = challenge_candidates[rank]
        chal_point = candidate_info["challenge_point"]

        # Find the selected solution point
        selected_sol = None
        for s in candidate_info["top_solutions"]:
            s_id = str(s.id) if (s.payload or {}).get("id") in (0, None) else str((s.payload or {}).get("id"))
            if s_id == best_sol_id:
                selected_sol = s
                break

        if not selected_sol:
            dropped_no_sol += 1
            logger.debug(
                "[build_pairs] rank=%s DROPPED: sol_id=%r not found in top_solutions (available: %s)",
                rank, best_sol_id,
                [str(s.id) if (s.payload or {}).get("id") in (0, None) else str((s.payload or {}).get("id")) for s in candidate_info["top_solutions"]]
            )
            continue

        # check if another challenge already claimed this solution in this batch
        if str(selected_sol.id) in used_solutions:
            dropped_dedup += 1
            logger.debug(
                "[build_pairs] rank=%s DROPPED: sol_id=%s already used (dedup)",
                rank, selected_sol.id
            )
            continue

        # Mark as used locally (so same-batch dedup works)
        used_challenges.add(str(chal_point.id))
        used_solutions.add(str(selected_sol.id))

        # Accumulate IDs for a single batched Redis write at the end
        accepted_challenge_ids.append(str(chal_point.id))
        accepted_solution_ids.append(str(selected_sol.id))

        chal_payload = chal_point.payload or {}
        sol_payload = selected_sol.payload or {}
        chal_meta = chal_payload.get("meta") or {}
        sol_meta = sol_payload.get("meta") or {}

        chal_id = chal_payload.get("id")
        if chal_id == 0 or chal_id is None:
            chal_id = chal_point.id

        sol_id = sol_payload.get("id")
        if sol_id == 0 or sol_id is None:
            sol_id = selected_sol.id

        item = {
            "rank": start_rank + len(validated_data),
            "match_score": round(selected_sol.score, 4),
            "challenge": {
                "id": chal_id,
                "text": chal_payload.get("statement"),
                "bot_type": chal_payload.get("bot_type"),
                "role": chal_meta.get("role") or "Women Leader",
                "district": chal_meta.get("district"),
                "state": chal_meta.get("state"),
            },
            "solution": {
                "id": sol_id,
                "text": sol_payload.get("statement"),
                "bot_type": sol_payload.get("bot_type"),
                "role": sol_meta.get("role"),
                "district": sol_meta.get("district"),
                "state": sol_meta.get("state"),
            },
        }

        validated_data.append(item)
        if len(validated_data) >= limit:
            dropped_limit = len(valid_results) - rank - 1
            break

    # Batch-persist accepted IDs to Redis
    if accepted_challenge_ids:
        await redis_cache.add_used_challenges(accepted_challenge_ids)
    if accepted_solution_ids:
        await redis_cache.add_used_solutions(accepted_solution_ids)

    logger.info(
        "[build_pairs] LLM passed=%s -> added=%s | dropped: sol_not_found=%s dedup=%s limit_cap=%s | total_valid=%s/%s",
        len(valid_results),
        len(valid_results) - dropped_no_sol - dropped_dedup - dropped_limit,
        dropped_no_sol, dropped_dedup, dropped_limit, len(validated_data), limit
    )

    return validated_data
