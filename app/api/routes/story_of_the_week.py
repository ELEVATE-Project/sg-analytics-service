from fastapi import APIRouter, Request, Depends, HTTPException
from ...core.config import settings
from ...cache import redis_cache
from ...services.story_of_the_week_service import get_story_of_the_week_from_db
from ...core.limiter import limiter
from ...api.schemas import StoryOfTheWeekQuery, StoryOfTheWeekResponse

router = APIRouter()


@router.get(
    "/api/v1/voices/story-of-the-week",
    response_model=StoryOfTheWeekResponse,
    status_code=200,
    summary="Get story of the week",
    description=(
        "Returns the top 54 story submissions (across all tenants) ordered by "
        "recency. Each row includes story_number for client-side week grouping. "
        "Results are cached."
    ),
)
@limiter.limit(settings.RATE_LIMIT)
async def get_story_of_the_week(request: Request, query: StoryOfTheWeekQuery = Depends()):
    """
    Fetch the story of the week entries.
    
    Returns the top story submissions ordered by recency. Results are cached
    and can be manually refreshed by passing the reset flag.
    """
    if query.reset:
        await redis_cache.flush_story_of_the_week_cache()

    cached = await redis_cache.get_cached_story_of_the_week()
    if cached is not None:
        return {"data": cached}

    data = await get_story_of_the_week_from_db()
    if data is not None:
        await redis_cache.set_cached_story_of_the_week(data)
        return {"data": data}

    raise HTTPException(status_code=500, detail="Failed to fetch story of the week")
