"""
app/core/logger.py
Structured logging via Loguru.
Outputs JSON in production, coloured text in development.
"""
import sys
from pathlib import Path

from loguru import logger as _logger

from app.core.config import get_settings


def setup_logger() -> None:
    """Configure Loguru sinks based on environment."""
    settings = get_settings()
    _logger.remove()  # Remove default handler

    log_format_dev = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    log_format_prod = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level} | {name}:{function}:{line} | {message} | {extra}"
    )

    if settings.is_production:
        # JSON sink to rotating file in production
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        _logger.add(
            log_dir / "lexai_{time:YYYY-MM-DD}.log",
            format=log_format_prod,
            level=settings.LOG_LEVEL,
            rotation="00:00",       # Daily rotation
            retention="30 days",
            compression="gz",
            serialize=True,         # JSON output
            backtrace=False,
            diagnose=False,         # Disable in prod (leaks locals)
            enqueue=True,           # Async-safe
        )
    else:
        # Coloured console in development
        _logger.add(
            sys.stdout,
            format=log_format_dev,
            level=settings.LOG_LEVEL,
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

        # Also write to file in dev for debugging
        _logger.add(
            "logs/lexai_dev.log",
            format=log_format_prod,
            level="DEBUG",
            rotation="10 MB",
            retention="7 days",
            serialize=True,
            enqueue=True,
        )


# Export a configured logger instance
setup_logger()
logger = _logger.bind(service="lexai-api")
