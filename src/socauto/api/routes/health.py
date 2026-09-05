"""Service health endpoint."""

from fastapi import APIRouter

from socauto.api.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
