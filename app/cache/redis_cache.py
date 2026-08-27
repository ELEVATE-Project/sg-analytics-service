import json
import logging
import redis.asyncio as redis
from ..core.config import settings

logger = logging.getLogger(__name__)

PAIRS_KEY         = "animations:pairs"
USED_CHALLENGES   = "animations:used_challenges"
USED_SOLUTIONS    = "animations:used_solutions"

_redis_client = None

def client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client

# Pairs cache
async def get_cached_pairs() -> list | None:
    """Return the cached pairs list, or None if the key is missing / expired."""
    try:
        raw = await client().get(PAIRS_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_pairs failed: %s", e)
        return None

async def set_cached_pairs(data: list) -> None:
    """Store pairs in Redis with the configured TTL."""
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        await client().setex(PAIRS_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_pairs failed: %s", e)

# Big Numbers cache
BIG_NUMBERS_KEY = "metrics:big_numbers"

async def get_cached_big_numbers() -> dict | None:
    try:
        raw = await client().get(BIG_NUMBERS_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_big_numbers failed: %s", e)
        return None

async def set_cached_big_numbers(data: dict) -> None:
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        await client().setex(BIG_NUMBERS_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_big_numbers failed: %s", e)

# Used-challenge / used-solution sets  (persist across restarts)
async def get_used_challenges() -> set:
    try:
        return set(await client().smembers(USED_CHALLENGES))
    except Exception as e:
        logger.warning("[redis_cache] get_used_challenges failed: %s", e)
        return set()

async def add_used_challenges(ids: list) -> None:
    if not ids:
        return
    try:
        await client().sadd(USED_CHALLENGES, *[str(i) for i in ids])
    except Exception as e:
        logger.warning("[redis_cache] add_used_challenges failed: %s", e)

async def get_used_solutions() -> set:
    try:
        return set(await client().smembers(USED_SOLUTIONS))
    except Exception as e:
        logger.warning("[redis_cache] get_used_solutions failed: %s", e)
        return set()

async def add_used_solutions(ids: list) -> None:
    if not ids:
        return
    try:
        await client().sadd(USED_SOLUTIONS, *[str(i) for i in ids])
    except Exception as e:
        logger.warning("[redis_cache] add_used_solutions failed: %s", e)

# Reset (called when ?reset=true)
async def flush_animations_cache() -> None:
    """Delete all animation cache keys from Redis."""
    try:
        await client().delete(PAIRS_KEY, USED_CHALLENGES, USED_SOLUTIONS)
        logger.info("[redis_cache] animations cache flushed")
    except Exception as e:
        logger.warning("[redis_cache] flush_animations_cache failed: %s", e)

async def flush_big_numbers_cache() -> None:
    """Delete the big-numbers cache key from Redis."""
    try:
        await client().delete(BIG_NUMBERS_KEY)
        logger.info("[redis_cache] big numbers cache flushed")
    except Exception as e:
        logger.warning("[redis_cache] flush_big_numbers_cache failed: %s", e)

# Themes cache
THEMES_KEY = "themes:top_with_voices"

async def get_cached_themes() -> list | None:
    try:
        raw = await client().get(THEMES_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_themes failed: %s", e)
        return None

async def set_cached_themes(data: list) -> None:
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        await client().setex(THEMES_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_themes failed: %s", e)

async def flush_themes_cache() -> None:
    try:
        await client().delete(THEMES_KEY)
        logger.info("[redis_cache] themes cache flushed")
    except Exception as e:
        logger.warning("[redis_cache] flush_themes_cache failed: %s", e)

# Theme Voices cache
def get_theme_voices_key(theme_id: str, page: int, page_size: int) -> str:
    return f"themes:{theme_id}:voices:{page}:{page_size}"

async def get_cached_theme_voices(theme_id: str, page: int, page_size: int) -> dict | None:
    try:
        key = get_theme_voices_key(theme_id, page, page_size)
        raw = await client().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_theme_voices failed: %s", e)
        return None

async def set_cached_theme_voices(theme_id: str, page: int, page_size: int, data: dict) -> None:
    try:
        key = get_theme_voices_key(theme_id, page, page_size)
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        await client().setex(key, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_theme_voices failed: %s", e)

async def flush_theme_voices_cache(theme_id: str) -> None:
    try:
        # Escape Redis glob metacharacters to prevent matching unintended keys
        for char in ['\\', '*', '?', '[', ']', '^', '-']:
            theme_id = theme_id.replace(char, f'\\{char}')
            
        keys = await client().keys(f"themes:{theme_id}:voices:*")
        if keys:
            await client().delete(*keys)
        logger.info(f"[redis_cache] theme voices cache flushed for {theme_id}")
    except Exception as e:
        logger.warning("[redis_cache] flush_theme_voices_cache failed: %s", e)

# Community Feed cache
COMMUNITY_FEED_KEY = "voices:community_feed"

async def get_cached_community_feed() -> list | None:
    try:
        raw = await client().get(COMMUNITY_FEED_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_community_feed failed: %s", e)
        return None

async def set_cached_community_feed(data: list) -> None:
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        await client().setex(COMMUNITY_FEED_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_community_feed failed: %s", e)

async def flush_community_feed_cache() -> None:
    try:
        await client().delete(COMMUNITY_FEED_KEY)
        logger.info("[redis_cache] community feed cache flushed")
    except Exception as e:
        logger.warning("[redis_cache] flush_community_feed_cache failed: %s", e)

# Story of the Week cache
STORY_OF_THE_WEEK_KEY = "voices:story_of_the_week"

async def get_cached_story_of_the_week() -> list | None:
    try:
        raw = await client().get(STORY_OF_THE_WEEK_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_story_of_the_week failed: %s", e)
        return None

async def set_cached_story_of_the_week(data: list) -> None:
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        await client().setex(STORY_OF_THE_WEEK_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_story_of_the_week failed: %s", e)

async def flush_story_of_the_week_cache() -> None:
    try:
        await client().delete(STORY_OF_THE_WEEK_KEY)
        logger.info("[redis_cache] story of the week cache flushed")
    except Exception as e:
        logger.warning("[redis_cache] flush_story_of_the_week_cache failed: %s", e)
