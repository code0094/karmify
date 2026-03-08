"""Global error handler for the bot."""

import structlog
from aiogram import Router
from aiogram.types import ErrorEvent

logger = structlog.get_logger()
router = Router()


@router.error()
async def global_error_handler(event: ErrorEvent) -> None:
    """Log all unhandled exceptions from handlers."""
    logger.error(
        "bot.unhandled_error",
        error=str(event.exception),
        update=str(event.update),
        exc_info=event.exception,
    )
