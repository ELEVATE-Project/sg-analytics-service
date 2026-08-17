from qdrant_client.http import models as qdrant_models
from ..core.config import settings
from ..database.qdrant import qdrant_client, get_async_qdrant_client

import numpy as np

def cosine_similarity(v1, v2):
    # Keep this around if used elsewhere, though we now vectorize in fetch_top_challenges
    v1, v2 = np.array(v1), np.array(v2)
    norm1, norm2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0: 
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))

def topic_of(text: str):
    """Return the matched topic key for a challenge's text."""
    if not text:
        return None
    lowered = text.lower()
    for topic, keywords in settings.TOPIC_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return topic
    return None

def fetch_top_challenges(used_challenges: set, limit: int = settings.FINAL_RESULT_SIZE):
    pool_size = 5000
    # Collect a candidate pool larger than `limit` so the diversity algorithm
    # actually has room to select the most semantically spread entries.
    # PRE_LLM_FETCH_SIZE is the configured upper bound for this pool.
    candidate_pool_limit = max(settings.PRE_LLM_FETCH_SIZE, limit)
    candidate_pool = []
    topic_counts = {}
    offset = None

    challenge_filter = qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(
                key="type", match=qdrant_models.MatchValue(value=settings.TYPE_CHALLENGE)
            ),
            qdrant_models.FieldCondition(
                key="embedded_score",
                range=qdrant_models.Range(gte=settings.MIN_MATCH_SCORE, lte=settings.MAX_MATCH_SCORE),
            ),
        ]
    )

    while len(candidate_pool) < candidate_pool_limit:
        points, next_offset = qdrant_client.scroll(
            collection_name=settings.MATCHING_COLLECTION,
            scroll_filter=challenge_filter,
            limit=pool_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
            order_by=qdrant_models.OrderBy(key="embedded_score", direction=qdrant_models.Direction.DESC),
        )

        if not points:
            break

        # Filter out anything we've already used (IDs are stored as strings in Redis)
        points = [p for p in points if str(p.id) not in used_challenges]

        for p in points:
            topic = topic_of(p.payload.get("statement", ""))
            if topic:
                if topic_counts.get(topic, 0) >= settings.MAX_PER_TOPIC:
                    continue
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            candidate_pool.append(p)

            if len(candidate_pool) >= candidate_pool_limit:
                break

        if next_offset is None:
            break
        offset = next_offset

    if not candidate_pool:
        return []

    # If the pool is not larger than the requested limit there is nothing for
    # the diversity algorithm to do — return the pool directly.
    if len(candidate_pool) <= limit:
        return candidate_pool

    # Convert vectors to a numpy array for vectorized distance computation
    all_vectors = np.array([p.vector for p in candidate_pool])
    # Normalize vectors to unit length so dot product == cosine similarity
    norms = np.linalg.norm(all_vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    all_vectors = all_vectors / norms

    selected_indices = [0]
    unselected_indices = list(range(1, len(candidate_pool)))

    while len(selected_indices) < limit and unselected_indices:
        # Compute similarity between all unselected and all currently selected
        unselected_vecs = all_vectors[unselected_indices]
        selected_vecs = all_vectors[selected_indices]

        # similarity matrix (len(unselected), len(selected))
        sims = np.dot(unselected_vecs, selected_vecs.T)

        # max similarity to any selected point for each unselected point
        max_sims = np.max(sims, axis=1)

        # pick the unselected point with the minimum max_sim
        best_local_idx = int(np.argmin(max_sims))

        selected_indices.append(unselected_indices[best_local_idx])
        unselected_indices.pop(best_local_idx)

    return [candidate_pool[i] for i in selected_indices]

def fetch_top_solutions(challenge_vector, limit: int = settings.SOLUTION_CANDIDATE_POOL_SIZE, score_threshold: float = None):
    # Default to the primary threshold from settings
    if score_threshold is None:
        score_threshold = settings.MIN_MATCH_SCORE

    # Base filter: only solution-type points
    must_conditions = [
        qdrant_models.FieldCondition(
            key="type", match=qdrant_models.MatchValue(value=settings.TYPE_SOLUTION)
        )
    ]

    # Apply bot_type filter when mode is "story" or "discussion".
    # "hybrid" means no restriction — fetch both types.
    if settings.SOLUTION_BOT_TYPE in ("story", "discussion"):
        must_conditions.append(
            qdrant_models.FieldCondition(
                key="bot_type",
                match=qdrant_models.MatchValue(value=settings.SOLUTION_BOT_TYPE),
            )
        )

    solution_filter = qdrant_models.Filter(must=must_conditions)

    response = qdrant_client.query_points(
        collection_name=settings.MATCHING_COLLECTION,
        query=challenge_vector,
        query_filter=solution_filter,
        limit=limit,
        with_payload=True,
        score_threshold=score_threshold,
    )
    return response.points


async def fetch_top_solutions_async(
    challenge_vector,
    limit: int = settings.SOLUTION_CANDIDATE_POOL_SIZE,
    score_threshold: float = None,
):
    """Async version of fetch_top_solutions — uses AsyncQdrantClient so the
    event loop is not blocked during network I/O. Callers can fire all
    per-challenge queries in parallel with asyncio.gather()."""
    if score_threshold is None:
        score_threshold = settings.MIN_MATCH_SCORE

    must_conditions = [
        qdrant_models.FieldCondition(
            key="type", match=qdrant_models.MatchValue(value=settings.TYPE_SOLUTION)
        )
    ]

    if settings.SOLUTION_BOT_TYPE in ("story", "discussion"):
        must_conditions.append(
            qdrant_models.FieldCondition(
                key="bot_type",
                match=qdrant_models.MatchValue(value=settings.SOLUTION_BOT_TYPE),
            )
        )

    solution_filter = qdrant_models.Filter(must=must_conditions)

    response = await get_async_qdrant_client().query_points(
        collection_name=settings.MATCHING_COLLECTION,
        query=challenge_vector,
        query_filter=solution_filter,
        limit=limit,
        with_payload=True,
        score_threshold=score_threshold,
    )
    return response.points
