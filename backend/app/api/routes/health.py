"""Health endpoints that do not require infrastructure dependencies."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return liveness for the foundation application."""

    return {"status": "ok"}
