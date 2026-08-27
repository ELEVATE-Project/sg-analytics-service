from fastapi import APIRouter, Request, Depends, HTTPException, Path
from ...core.config import settings
from ...cache import redis_cache
from ...services.themes_service import get_top_themes_with_voices_from_db, get_theme_voices_paginated_from_db
from ...core.limiter import limiter
from ...api.schemas import ThemeQuery, ThemeVoiceQuery, ThemesResponse, ThemeVoicesPaginatedResponse

router = APIRouter()

@router.get(
    "/api/v1/voices/themes",
    response_model=ThemesResponse,
    status_code=200,
    summary="Get top themes with voices",
    description="Returns top themes with up to 4 voices each.",
)
@limiter.limit(settings.RATE_LIMIT)
async def get_top_themes(request: Request, query: ThemeQuery = Depends()):
    """
    Fetch the top themes along with up to 4 voices each.
    
    Retrieves the top aggregated themes. Results are cached and can be reset
    using the query parameters.
    """
    if query.reset:
        await redis_cache.flush_themes_cache()

    cached = await redis_cache.get_cached_themes()
    if cached is not None:
        return {"data": cached}

    data = await get_top_themes_with_voices_from_db()
    if data is not None:
        await redis_cache.set_cached_themes(data)
        return {"data": data}

    raise HTTPException(status_code=500, detail="Failed to fetch themes")

@router.get(
    "/api/v1/voices/themes/{theme_id}",
    response_model=ThemeVoicesPaginatedResponse,
    status_code=200,
    summary="Get paginated voices for a theme",
    description="Returns paginated voices for a specific theme.",
)
@limiter.limit(settings.RATE_LIMIT)
async def get_theme_voices(
    request: Request, 
    theme_id: str = Path(..., title="The ID of the theme"),
    query: ThemeVoiceQuery = Depends()
):
    """
    Fetch paginated voices for a specific theme.
    
    Retrieves paginated voices associated with the provided theme ID.
    Supports cache resetting per page via query parameters.
    """
    if query.reset:
        await redis_cache.flush_theme_voices_cache(theme_id)

    cached = await redis_cache.get_cached_theme_voices(theme_id, query.page, query.page_size)
    if cached is not None:
        return {"data": cached}

    data = await get_theme_voices_paginated_from_db(theme_id, query.page, query.page_size)
    if data is not None:
        await redis_cache.set_cached_theme_voices(theme_id, query.page, query.page_size, data)
        return {"data": data}

    raise HTTPException(status_code=500, detail="Failed to fetch theme voices")
