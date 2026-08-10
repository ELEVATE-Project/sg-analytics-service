"""
Redis cache client — thin wrapper around redis-py.

Keys used:
  animations:pairs          – JSON list of validated pairs (TTL = CACHE_TTL_HOURS)
  animations:used_challenges – Redis Set of Qdrant point IDs already consumed
  animations:used_solutions  – Redis Set of Qdrant point IDs already consumed
"""
import json
import logging
import redis
from ..config import settings

logger = logging.getLogger(__name__)

PAIRS_KEY         = "animations:pairs"
USED_CHALLENGES   = "animations:used_challenges"
USED_SOLUTIONS    = "animations:used_solutions"

def client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

# ---------------------------------------------------------------------------
# Pairs cache
# ---------------------------------------------------------------------------

def get_cached_pairs() -> list | None:
    """Return the cached pairs list, or None if the key is missing / expired."""
    try:
        raw = client().get(PAIRS_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_pairs failed: %s", e)
        return None

def set_cached_pairs(data: list) -> None:
    """Store pairs in Redis with the configured TTL."""
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        client().setex(PAIRS_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_pairs failed: %s", e)

# ---------------------------------------------------------------------------
# Big Numbers cache
# ---------------------------------------------------------------------------
BIG_NUMBERS_KEY = "metrics:big_numbers"

def get_cached_big_numbers() -> dict | None:
    try:
        raw = client().get(BIG_NUMBERS_KEY)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("[redis_cache] get_cached_big_numbers failed: %s", e)
        return None

def set_cached_big_numbers(data: dict) -> None:
    try:
        ttl_seconds = int(settings.CACHE_TTL_HOURS * 3600)
        client().setex(BIG_NUMBERS_KEY, ttl_seconds, json.dumps(data))
    except Exception as e:
        logger.warning("[redis_cache] set_cached_big_numbers failed: %s", e)

# ---------------------------------------------------------------------------
# Used-challenge / used-solution sets  (persist across restarts)
# ---------------------------------------------------------------------------

def get_used_challenges() -> set:
    try:
        return set(client().smembers(USED_CHALLENGES))
    except Exception as e:
        logger.warning("[redis_cache] get_used_challenges failed: %s", e)
        return set()

def add_used_challenges(ids: list) -> None:
    if not ids:
        return
    try:
        client().sadd(USED_CHALLENGES, *[str(i) for i in ids])
    except Exception as e:
        logger.warning("[redis_cache] add_used_challenges failed: %s", e)

def get_used_solutions() -> set:
    try:
        return set(client().smembers(USED_SOLUTIONS))
    except Exception as e:
        logger.warning("[redis_cache] get_used_solutions failed: %s", e)
        return set()

def add_used_solutions(ids: list) -> None:
    if not ids:
        return
    try:
        client().sadd(USED_SOLUTIONS, *[str(i) for i in ids])
    except Exception as e:
        logger.warning("[redis_cache] add_used_solutions failed: %s", e)

# ---------------------------------------------------------------------------
# Reset (called when ?reset=true)
# ---------------------------------------------------------------------------

def flush_cache() -> None:
    """Delete all animation cache keys from Redis."""
    try:
        client().delete(PAIRS_KEY, USED_CHALLENGES, USED_SOLUTIONS, BIG_NUMBERS_KEY)
        logger.info("[redis_cache] cache flushed")
    except Exception as e:
        logger.warning("[redis_cache] flush_cache failed: %s", e)
