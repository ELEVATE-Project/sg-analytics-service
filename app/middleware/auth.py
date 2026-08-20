import logging
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.config import settings

logger = logging.getLogger(__name__)

# Routes that are exempt from token validation (e.g. health checks).
EXEMPT_PATHS: set[str] = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthTokenMiddleware(BaseHTTPMiddleware):
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

        token = request.headers.get("X-Auth-Token", "")
        if not token or not secrets.compare_digest(token, settings.API_TOKEN):
            logger.warning(
                "Rejected request to %s – invalid or missing X-Auth-Token "
                "(origin=%s, ip=%s)",
                request.url.path,
                request.headers.get("origin", "—"),
                request.client.host if request.client else "—",
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "detail": "Missing or invalid X-Auth-Token header.",
                },
            )

        return await call_next(request)
