"""
app/core/exceptions.py
Custom domain exceptions and FastAPI exception handlers.
All exceptions carry a machine-readable error_code for client consumption.
"""
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logger import logger


# ─────────────────────────────────────────────────────────────
#  Base Exception
# ─────────────────────────────────────────────────────────────

class LexAIException(Exception):
    """Base exception for all domain errors."""

    def __init__(
        self,
        message: str,
        error_code: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


# ─────────────────────────────────────────────────────────────
#  Domain Exceptions
# ─────────────────────────────────────────────────────────────

class AnalysisNotFoundException(LexAIException):
    def __init__(self, analysis_id: str) -> None:
        super().__init__(
            message=f"Analysis '{analysis_id}' not found.",
            error_code="ANALYSIS_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"analysis_id": analysis_id},
        )


class AnalysisFailedException(LexAIException):
    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"Legal analysis failed: {reason}",
            error_code="ANALYSIS_FAILED",
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"reason": reason},
        )


class FileExtractionException(LexAIException):
    def __init__(self, filename: str, reason: str) -> None:
        super().__init__(
            message=f"Failed to extract text from '{filename}': {reason}",
            error_code="FILE_EXTRACTION_FAILED",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"filename": filename, "reason": reason},
        )


class UnsupportedFileTypeException(LexAIException):
    def __init__(self, extension: str, allowed: list[str]) -> None:
        super().__init__(
            message=f"File type '{extension}' is not supported.",
            error_code="UNSUPPORTED_FILE_TYPE",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            details={"extension": extension, "allowed": allowed},
        )


class FileTooLargeException(LexAIException):
    def __init__(self, size_mb: float, max_mb: int) -> None:
        super().__init__(
            message=f"File size {size_mb:.1f}MB exceeds maximum {max_mb}MB.",
            error_code="FILE_TOO_LARGE",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            details={"size_mb": size_mb, "max_mb": max_mb},
        )


class RateLimitExceededException(LexAIException):
    def __init__(self, limit: str, retry_after: int = 60) -> None:
        super().__init__(
            message=f"Rate limit exceeded. Limit: {limit}.",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"limit": limit, "retry_after_seconds": retry_after},
        )


class AnthropicAPIException(LexAIException):
    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"AI service error: {reason}",
            error_code="AI_SERVICE_ERROR",
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"reason": reason},
        )


class InvalidJurisdictionException(LexAIException):
    def __init__(self, jurisdiction: str) -> None:
        super().__init__(
            message=f"Jurisdiction '{jurisdiction}' is not supported.",
            error_code="INVALID_JURISDICTION",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"jurisdiction": jurisdiction},
        )


class ScenarioTooShortException(LexAIException):
    def __init__(self, length: int, minimum: int) -> None:
        super().__init__(
            message=f"Scenario text is too short ({length} chars). Minimum: {minimum}.",
            error_code="SCENARIO_TOO_SHORT",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"length": length, "minimum": minimum},
        )


class DatabaseException(LexAIException):
    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(
            message=f"Database error during '{operation}'.",
            error_code="DATABASE_ERROR",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"operation": operation, "reason": reason},
        )


class CacheException(LexAIException):
    def __init__(self, reason: str) -> None:
        super().__init__(
            message=f"Cache operation failed: {reason}",
            error_code="CACHE_ERROR",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"reason": reason},
        )


# ─────────────────────────────────────────────────────────────
#  FastAPI Exception Handlers
# ─────────────────────────────────────────────────────────────

def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": error_code,
                "message": message,
                "details": details or {},
            },
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all custom exception handlers to the FastAPI app."""

    @app.exception_handler(LexAIException)
    async def lexai_exception_handler(request: Request, exc: LexAIException) -> JSONResponse:
        logger.warning(
            "Domain exception",
            error_code=exc.error_code,
            message=exc.message,
            path=request.url.path,
            details=exc.details,
        )
        return _error_response(exc.status_code, exc.error_code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("Request validation failed", errors=exc.errors(), path=request.url.path)
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        logger.warning("HTTP exception", status_code=exc.status_code, path=request.url.path)
        return _error_response(
            status_code=exc.status_code,
            error_code="HTTP_ERROR",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", path=request.url.path, exc=str(exc))
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            message="An unexpected error occurred. Please try again.",
        )
