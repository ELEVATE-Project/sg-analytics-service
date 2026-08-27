from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from .core.config import settings
from .core.limiter import limiter
from .core.logging_config import setup_logging
from .api.routes import animations, metrics, themes, community_feed, story_of_the_week
from .middleware.observability import ObservabilityMiddleware
from .middleware.auth import AuthTokenMiddleware
import logging
from sqlalchemy import text
from .database.postgres import get_engine
from .database.qdrant import get_async_qdrant_client
from .cache.redis_cache import client as get_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs setup_logging() before the server starts accepting requests."""
    setup_logging()
    logger = logging.getLogger("app.startup")
    
    logger.info("Starting API...")
    
    # Check Postgres
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Postgres connected successfully.")
    except Exception as e:
        logger.error(f"Postgres connection failed: {e}")
        raise

    # Check Redis
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        logger.info("Redis connected successfully.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

    # Check Qdrant
    try:
        qdrant_client = get_async_qdrant_client()
        await qdrant_client.get_collections()
        logger.info("Qdrant connected successfully.")
    except Exception as e:
        logger.error(f"Qdrant connection failed: {e}")
        raise
        
    logger.info("API connected and ready.")
    
    yield

async def global_headers(
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token", description="API Authentication Token"),
):
    pass

app = FastAPI(title="SG Voices API's", lifespan=lifespan, dependencies=[Depends(global_headers)])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.ALLOWED_METHODS,
    allow_headers=settings.ALLOWED_HEADERS,
)

@app.middleware("http")
async def origin_guard(request: Request, call_next):

    origin = request.headers.get("origin", "")
    if not origin:
        return await call_next(request)

    if not origin.startswith("http"):
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin not in settings.ALLOWED_ORIGINS:
        return JSONResponse(
            status_code=403,
            content={
                "error": "Forbidden",
                "detail": f"Origin '{origin}' is not in the allowed origins list.",
            },
        )

    return await call_next(request)

app.add_middleware(ObservabilityMiddleware)
app.add_middleware(AuthTokenMiddleware)
app.add_middleware(SlowAPIMiddleware)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "message": "API is healthy"}

# Include routers
app.include_router(animations.router)
app.include_router(metrics.router)
app.include_router(themes.router)
app.include_router(community_feed.router)
app.include_router(story_of_the_week.router)
