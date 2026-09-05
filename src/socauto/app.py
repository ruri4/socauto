"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from socauto import __version__
from socauto.api.routes.health import router as health_router
from socauto.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with explicit runtime dependencies."""
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        app_settings.prepare_runtime()
        yield

    application = FastAPI(
        title="socauto",
        summary="Social media republishing automation API",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.include_router(health_router)
    return application


app = create_app()
