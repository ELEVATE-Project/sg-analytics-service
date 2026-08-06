import json
import time
import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import text

from ..database.connection import async_session

logger = logging.getLogger(__name__)

async def set_body(request: Request, body: bytes):
    async def receive():
        return {"type": "http.request", "body": body}
    request._receive = receive

async def get_body(request: Request) -> bytes:
    body = await request.body()
    await set_body(request, body)
    return body

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # 1. Capture request body
        req_body = await get_body(request)
        req_json = None
        try:
            if req_body:
                req_json = json.loads(req_body.decode('utf-8'))
        except Exception:
            pass # ignore parse errors for non-json bodies

        # 2. Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Unhandled exceptions
            duration_ms = int((time.time() - start_time) * 1000)
            asyncio.create_task(
                log_api_call(
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=500,
                    duration_ms=duration_ms,
                    req_payload=req_json,
                    res_payload=None,
                    client_ip=request.client.host if request.client else None,
                    error_msg=str(e)
                )
            )
            raise e

        # 3. Capture response body
        res_json = None
        if not isinstance(response, StreamingResponse):
            # Attempt to read response body if available (e.g. JSONResponse)
            if hasattr(response, "body"):
                try:
                    res_json = json.loads(response.body.decode('utf-8'))
                except Exception:
                    pass
        else:
            # For streaming responses, we can't easily capture the body without breaking the stream
            pass

        duration_ms = int((time.time() - start_time) * 1000)
        
        # 4. Asynchronously log the API call
        task = BackgroundTask(
            log_api_call,
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            req_payload=req_json,
            res_payload=res_json,
            client_ip=request.client.host if request.client else None,
            error_msg=None
        )
        response.background = task
        
        return response

async def log_api_call(endpoint: str, method: str, status_code: int, duration_ms: int, req_payload: dict | None, res_payload: dict | None, client_ip: str | None, error_msg: str | None):
    try:
        async with async_session() as session:
            query = text("""
                INSERT INTO api_observability (endpoint, method, status_code, duration_ms, request_payload, response_payload, client_ip, error_message)
                VALUES (:endpoint, :method, :status_code, :duration_ms, :req_payload, :res_payload, :client_ip, :error_msg)
            """)
            await session.execute(query, {
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "req_payload": json.dumps(req_payload) if req_payload else None,
                "res_payload": json.dumps(res_payload) if res_payload else None,
                "client_ip": client_ip,
                "error_msg": error_msg
            })
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to log API call to DB: {e}")
