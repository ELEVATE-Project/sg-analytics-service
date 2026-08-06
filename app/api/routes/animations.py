from fastapi import APIRouter, Query, Request
from ...config import settings
from ...cache import redis_cache
from ...services.matching_service import build_pairs
from ...limiter import limiter

router = APIRouter()

@router.get("/api/v1/voices/animations")
@limiter.limit(settings.RATE_LIMIT)
def get_animations(request: Request, limit: int = Query(settings.FINAL_RESULT_SIZE), reset: bool = Query(False)):
    if reset:
        redis_cache.flush_cache()

    cached = redis_cache.get_cached_pairs()
    if cached is not None:
        return {"data": cached[:limit]}

    data = build_pairs(limit=limit)
    if data:
        redis_cache.set_cached_pairs(data)

    return {"data": data}
