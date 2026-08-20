from fastapi import APIRouter, Request, Depends
from ...core.config import settings
from ...cache import redis_cache
from ...services.matching_service import build_pairs
from ...core.limiter import limiter
from ...api.schemas import AnimationsQuery, AnimationsResponse

router = APIRouter()


@router.get(
    "/api/v1/voices/animations",
    response_model=AnimationsResponse,
    status_code=200,
    summary="Get validated challenge-solution animation pairs",
    description=(
        "Returns up to `limit` challenge-solution pairs from the Redis cache. "
        "On a cache miss the pairs are built on-demand via Qdrant + Gemini LLM validation "
        "and cached for `CACHE_TTL_HOURS`. Pass `reset=true` to evict the cache and "
        "force a fresh build."
    ),
)
@limiter.limit(settings.RATE_LIMIT)
async def get_animations(request: Request, query: AnimationsQuery = Depends()):
    """Return validated animation pairs, using Redis cache when available."""
    limit = min(max(1, query.limit), settings.FINAL_RESULT_SIZE)

    if query.reset:
        await redis_cache.flush_animations_cache()

    cached = await redis_cache.get_cached_pairs()
    if cached is not None:
        return {"data": cached[:limit]}

    data = await build_pairs(limit=settings.FINAL_RESULT_SIZE)
    if data:
        await redis_cache.set_cached_pairs(data)

    return {"data": data[:limit]}
