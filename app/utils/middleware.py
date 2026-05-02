"""
app/utils/middleware.py
Request/response logging middleware.
Logs method, path, status code, and duration for every request.
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logger import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured per-request logging with correlation IDs."""

    SKIP_PATHS = {"/health", "/ready", "/live", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        start      = time.perf_counter()

        # Attach request_id to all logs within this request
        with logger.contextualize(request_id=request_id):
            logger.info(
                "→ Request",
                method=request.method,
                path=request.url.path,
                client=request.client.host if request.client else "unknown",
            )

            try:
                response = await call_next(request)
                duration_ms = round((time.perf_counter() - start) * 1000, 2)

                log_fn = logger.info if response.status_code < 400 else logger.warning
                log_fn(
                    "← Response",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=duration_ms,
                )
                response.headers["X-Request-ID"]    = request_id
                response.headers["X-Response-Time"] = f"{duration_ms}ms"
                return response

            except Exception as exc:
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                logger.exception(
                    "Request failed",
                    method=request.method,
                    path=request.url.path,
                    duration_ms=duration_ms,
                    exc=str(exc),
                )
                raise
