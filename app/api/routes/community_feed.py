from fastapi import APIRouter, Request, HTTPException, Query
from ...core.config import settings
from ...cache import redis_cache
from ...services.community_feed_service import get_community_feed_from_db
from ...core.limiter import limiter
from ...api.schemas import CommunityFeedQuery, CommunityFeedResponse

router = APIRouter()


@router.get(
    "/api/v1/voices/community-feed",
    response_model=CommunityFeedResponse,
    status_code=200,
    summary="Get community feed stories",
    description=(
        "Returns up to 20 most recent stories that have both "
        "action_steps and impact populated, ordered by submission date descending."
    ),
)
@limiter.limit(settings.RATE_LIMIT)
async def get_community_feed(request: Request, query: CommunityFeedQuery = Query()):
    """
    Fetch the community feed stories.
    
    Returns up to 20 most recent stories with action_steps and impact populated.
    Rejects any unknown query parameters.
    """
    if query.reset:
        await redis_cache.flush_community_feed_cache()

    cached = await redis_cache.get_cached_community_feed()
    if cached is not None:
        return {"data": cached}

    data = await get_community_feed_from_db()
    if data is not None:
        await redis_cache.set_cached_community_feed(data)
        return {"data": data}

    raise HTTPException(status_code=500, detail="Failed to fetch community feed")
