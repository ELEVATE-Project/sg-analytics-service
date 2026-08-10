from fastapi import APIRouter, Query, Request, HTTPException
from ...config import settings
from ...cache import redis_cache
from ...services.metrics_service import get_big_numbers_from_db
from ...limiter import limiter

router = APIRouter()

@router.get("/api/v1/voices/big-numbers")
@limiter.limit(settings.RATE_LIMIT)
async def get_big_numbers(request: Request, reset: bool = Query(False)):
    if reset:
        redis_cache.flush_cache()

    cached = redis_cache.get_cached_big_numbers()
    if cached is not None:
        return {"data": cached}

    data = await get_big_numbers_from_db()
    if data is not None:
        redis_cache.set_cached_big_numbers(data)
        return {"data": data}
    
    raise HTTPException(status_code=500, detail="Failed to fetch big numbers")
