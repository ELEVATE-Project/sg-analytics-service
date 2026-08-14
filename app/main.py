from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from .core.config import settings
from .core.limiter import limiter
from .core.logging_config import setup_logging
from .api.routes import animations, metrics
from .middleware.observability import ObservabilityMiddleware
from .middleware.auth import AuthTokenMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs setup_logging() before the server starts accepting requests."""
    setup_logging()
    yield

app = FastAPI(title="SG Voices API's", lifespan=lifespan)
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

# Include routers
app.include_router(animations.router)
app.include_router(metrics.router)
