import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.background import BackgroundTask, BackgroundTasks
from sqlalchemy import text

from ..database.connection import async_session

logger = logging.getLogger(__name__)

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        origin = request.headers.get("origin")
        triggered_by = "cron_job" if request.headers.get("x-triggered-by") == "cron" else "direct_call"
        client_ip = request.client.host if request.client else None

        try:
            response = await call_next(request)

            # Determine status
            if response.headers.get("X-Cache-Hit") == "true":
                status = "cache_hit"
            elif 200 <= response.status_code < 300:
                status = "success"
            else:
                status = "failure"

            # Populate error_msg for every non-2xx response (3xx redirects and 4xx/5xx errors)
            error_msg = (
                f"HTTP {response.status_code}" if response.status_code >= 300 else None
            )

            duration_ms = int((time.time() - start_time) * 1000)

            log_task = BackgroundTask(
                log_api_call,
                endpoint=request.url.path,
                method=request.method,
                origin=origin,
                client_ip=client_ip,
                triggered_by=triggered_by,
                status=status,
                status_code=response.status_code,
                duration_ms=duration_ms,
                error_msg=error_msg,
            )

            # Compose with any existing background task on the response
            existing = getattr(response, "background", None)
            if existing is None:
                response.background = log_task
            else:
                tasks = BackgroundTasks()
                tasks.add_task(existing.func, *existing.args, **existing.kwargs)
                tasks.add_task(log_task.func, *log_task.args, **log_task.kwargs)
                response.background = tasks

            return response

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            # Cannot attach to response here — run as a fire-and-forget coroutine
            # wrapped inside a BackgroundTask so it stays within the ASGI lifecycle.
            log_task = BackgroundTask(
                log_api_call,
                endpoint=request.url.path,
                method=request.method,
                origin=origin,
                client_ip=client_ip,
                triggered_by=triggered_by,
                status="failure",
                status_code=500,
                duration_ms=duration_ms,
                error_msg=str(e),
            )
            await log_task()
            raise e

async def log_api_call(
    endpoint: str,
    method: str,
    origin: str | None,
    client_ip: str | None,
    triggered_by: str,
    status: str,
    status_code: int,
    duration_ms: int,
    error_msg: str | None,
):
    try:
        async with async_session() as session:
            # Note the exact spelling from the DB schema: triggred_by, duraion_ms
            query = text("""
                INSERT INTO api_observability
                (endpoint, method, origin, triggred_by, status, status_code, duraion_ms, error_message)
                VALUES
                (:endpoint, :method, :origin, :triggred_by, :status, :status_code, :duraion_ms, :error_msg)
            """)
            await session.execute(query, {
                "endpoint": endpoint,
                "method": method,
                "origin": origin,
                "triggred_by": triggered_by,
                "status": status,
                "status_code": status_code,
                "duraion_ms": duration_ms,
                "error_msg": error_msg,
            })
            await session.commit()
    except Exception as e:
        logger.error("Failed to log API call to DB: %s", e)
