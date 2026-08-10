import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import settings

logger = logging.getLogger(__name__)

# Routes that are exempt from token validation (e.g. health checks).
EXEMPT_PATHS: set[str] = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthTokenMiddleware(BaseHTTPMiddleware):
    """Validates the X-API-Token header on every incoming request.

    Enforcement rules:
    - OPTIONS (CORS preflight) requests are always passed through.
    - Requests to exempt paths (docs, health) are passed through.
    - If settings.API_TOKEN is blank the server will start, but EVERY
      non-exempt request will be rejected – this forces operators to set
      the token before going to production.
    - Any request missing the header, or carrying the wrong value,
      receives a 401 Unauthorized response.
    """

    async def dispatch(self, request: Request, call_next):
        # Always allow CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow exempt paths (docs, health, etc.)
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # Warn loudly if no token is configured
        if not settings.API_TOKEN:
            logger.warning(
                "API_TOKEN is not set – all non-exempt requests are being rejected."
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service misconfigured",
                    "detail": "API_TOKEN is not configured on the server.",
                },
            )

        token = request.headers.get("X-API-Token", "")
        if not token or token != settings.API_TOKEN:
            logger.warning(
                "Rejected request to %s – invalid or missing X-API-Token "
                "(origin=%s, ip=%s)",
                request.url.path,
                request.headers.get("origin", "—"),
                request.client.host if request.client else "—",
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "detail": "Missing or invalid X-API-Token header.",
                },
            )

        return await call_next(request)
