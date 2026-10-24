import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.session import init_db
from app.live.service import LiveService, set_live_service
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        init_db()
    except Exception:
        # Keep serving so /api/health can report the problem.
        logger.exception("Database initialisation failed - is PostgreSQL running and DATABASE_URL correct?")
    logger.info("Started in %s mode (trading_mode=%s, coach_mode=%s)", settings.environment,
                settings.trading_mode, settings.coach_mode)
    live = LiveService(settings, manager)
    set_live_service(live)
    await live.start()
    logger.info("Live engine: %s", live.status.message)
    try:
        yield
    finally:
        await live.stop()
        set_live_service(None)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="Machine-learning trading assistant for forex pairs and spot metals. Paper trading only. Signals are statistical model outputs, not guarantees.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
