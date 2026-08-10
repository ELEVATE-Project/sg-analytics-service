import time
import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.background import BackgroundTask
from sqlalchemy import text

from ..database.connection import async_session

logger = logging.getLogger(__name__)

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        origin = request.headers.get("origin")
        # Default to direct_call, unless a custom header says otherwise
        triggered_by = "cron_job" if request.headers.get("x-triggered-by") == "cron" else "direct_call"
        
        try:
            response = await call_next(request)
            
            # Determine status
            # If our cache logic sets a custom header, we can log it as a cache hit
            if response.headers.get("X-Cache-Hit") == "true":
                status = "cache_hit"
            elif 200 <= response.status_code < 400:
                status = "success"
            else:
                status = "failure"
                
            duration_ms = int((time.time() - start_time) * 1000)
            
            task = BackgroundTask(
                log_api_call,
                endpoint=request.url.path,
                method=request.method,
                origin=origin,
                triggered_by=triggered_by,
                status=status,
                status_code=response.status_code,
                duration_ms=duration_ms,
                error_msg=None
            )
            
            # Starlette responses can have background tasks attached
            if getattr(response, "background", None) is None:
                response.background = task
            else:
                # If there's already a background task, we'd theoretically need to chain them,
                # but FastAPI usually handles single background tasks. To be safe, we'll
                # just run ours manually if one already exists.
                asyncio.create_task(
                    log_api_call(
                        endpoint=request.url.path,
                        method=request.method,
                        origin=origin,
                        triggered_by=triggered_by,
                        status=status,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                        error_msg=None
                    )
                )

            return response
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            asyncio.create_task(
                log_api_call(
                    endpoint=request.url.path,
                    method=request.method,
                    origin=origin,
                    triggered_by=triggered_by,
                    status="failure",
                    status_code=500,
                    duration_ms=duration_ms,
                    error_msg=str(e)
                )
            )
            raise e

async def log_api_call(endpoint: str, method: str, origin: str | None, triggered_by: str, status: str, status_code: int, duration_ms: int, error_msg: str | None):
    try:
        async with async_session() as session:
            # Note the exact spelling from the image schema: triggred_by, duraion_ms
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
                "error_msg": error_msg
            })
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to log API call to DB: {e}")
