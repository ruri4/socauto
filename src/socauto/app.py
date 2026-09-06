"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from socauto import __version__
from socauto.api.errors import ErrorResponse, install_error_handlers
from socauto.api.routes.accounts import router as accounts_router
from socauto.api.routes.health import router as health_router
from socauto.api.routes.jobs import router as jobs_router
from socauto.config import Settings, get_settings
from socauto.db.engine import create_db_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with explicit runtime dependencies."""
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        app_settings.prepare_runtime()
        engine = create_db_engine(app_settings)
        application.state.engine = engine
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title="socauto",
        summary="Social media republishing automation API",
        version=__version__,
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    application.state.settings = app_settings
    install_error_handlers(application)
    application.include_router(health_router)
    application.include_router(accounts_router)
    application.include_router(jobs_router)
    return application


app = create_app()
