import json
import logging
from datetime import datetime
from pathlib import Path
from ..config import settings
from ..cache import redis_cache
from .qdrant_service import fetch_top_challenges, fetch_top_solutions
from .llm_service import validate_pairs_with_llm

logger = logging.getLogger(__name__)

def payload_record_id(point):
    payload_id = (point.payload or {}).get("id")
    return str(point.id) if payload_id == 0 or payload_id is None else payload_id

def solution_debug_item(solution_point, mapped_solution_id=None):
    payload = solution_point.payload or {}
    meta = payload.get("meta") or {}
    return {
        "point_id": str(solution_point.id),
        "id": payload_record_id(solution_point),
        "score": round(solution_point.score, 4),
        "mapped": solution_point.id == mapped_solution_id,
        "text": payload.get("statement"),
        "bot_type": payload.get("bot_type"),
        "role": meta.get("role"),
        "district": meta.get("district"),
        "state": meta.get("state"),
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
        if solution.id in used_solutions:
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
    chal_meta = chal_payload.get("meta") or {}
    mapped_solution_id = mapped_solution.id if mapped_solution else None
    debug_payload = {
        "challenge": {
            "point_id": str(challenge_point.id),
            "id": payload_record_id(challenge_point),
            "embedded_score": round(chal_payload.get("embedded_score", 0.0), 4),
            "text": chal_payload.get("statement"),
            "district": chal_meta.get("district"),
            "state": chal_meta.get("state"),
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


def build_pairs(limit: int = settings.FINAL_RESULT_SIZE) -> list:
    validated_data = []

    # --- Load used sets from Redis ---
    used_challenges = redis_cache.get_used_challenges()
    used_solutions  = redis_cache.get_used_solutions()
    start_rank = len(used_challenges) + 1

    local_used_challenges = set(used_challenges)

    while len(validated_data) < limit:
        challenges = fetch_top_challenges(local_used_challenges, limit=settings.PRE_LLM_FETCH_SIZE)
        if not challenges:
            logger.info("[build_pairs] Exhausted challenges from DB. Stopping early.")
            break
            
        # Mark fetched challenges as locally used so next loop iteration fetches fresh ones
        for c in challenges:
            local_used_challenges.add(c.id)

        debug_log_file = new_top_solutions_debug_log_file()
        logger.info("[pre_llm_fetch] writing full JSON logs to %s", debug_log_file)

        challenge_candidates = []
        llm_payload = []
        
        for i, chal_point in enumerate(challenges):
            # --- Primary fetch (MIN_MATCH_SCORE) ---
            solutions = fetch_top_solutions(chal_point.vector)
            used_threshold = settings.MIN_MATCH_SCORE

            # --- Fallback fetch (FALLBACK_MATCH_SCORE) if primary returned nothing ---
            if not solutions:
                solutions = fetch_top_solutions(
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

            # We'll log the top scored solution as mapped_solution for debug compatibility
            best_sol_fallback = top_sols[0] if top_sols else None
            print_top_solution_debug(chal_point, solutions, best_sol_fallback, debug_log_file)

            if top_sols:
                rank = len(challenge_candidates)
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
            logger.info("[build_pairs] No challenge candidates found in this batch, continuing to next batch.")
            continue

        valid_results = validate_pairs_with_llm(llm_payload)

        dropped_no_sol  = 0   # LLM chose a sol_id we can't find in top_solutions
        dropped_dedup   = 0   # solution already used by another challenge in this batch
        dropped_limit   = 0   # hit FINAL_RESULT_SIZE cap

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

            # Persist to Redis
            redis_cache.add_used_challenges([chal_point.id])
            redis_cache.add_used_solutions([selected_sol.id])
            
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

        logger.info(
            "[build_pairs] LLM passed=%s → added=%s | dropped: sol_not_found=%s dedup=%s limit_cap=%s | total_valid=%s/%s",
            len(valid_results), len(valid_results) - dropped_no_sol - dropped_dedup - dropped_limit,
            dropped_no_sol, dropped_dedup, dropped_limit, len(validated_data), limit
        )

    return validated_data
