from fastapi import APIRouter, Request, Depends, HTTPException
from ...core.config import settings
from ...cache import redis_cache
from ...services.metrics_service import get_big_numbers_from_db
from ...core.limiter import limiter
from ...api.schemas import BigNumbersQuery, BigNumbersResponse

router = APIRouter()


@router.get(
    "/api/v1/voices/big-numbers",
    response_model=BigNumbersResponse,
    status_code=200,
    summary="Get aggregated big-number metrics",
    description=(
        "Returns aggregated metrics (big numbers) from PostgreSQL with a Redis caching layer. "
        "Pass `reset=true` to evict the cache and force a fresh DB read."
    ),
)
@limiter.limit(settings.RATE_LIMIT)
async def get_big_numbers(request: Request, query: BigNumbersQuery = Depends()):
    """Return cached big-number metrics, falling back to a live DB query."""
    if query.reset:
        await redis_cache.flush_big_numbers_cache()

    cached = await redis_cache.get_cached_big_numbers()
    if cached is not None:
        return {"data": cached}

    data = await get_big_numbers_from_db()
    if data is not None:
        await redis_cache.set_cached_big_numbers(data)
        return {"data": data}

    raise HTTPException(status_code=500, detail="Failed to fetch big numbers")
