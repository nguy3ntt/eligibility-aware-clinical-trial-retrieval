"""FastAPI application entry point."""

from fastapi import FastAPI

from backend.app.api.routes.health import router as health_router
from backend.app.core.config import settings

app = FastAPI(
    title="Eligibility-Aware Clinical Trial Retrieval API",
    description=(
        "Research API for explainable clinical-trial retrieval using synthetic patient cases."
    ),
    version="0.1.0",
)
app.include_router(health_router)


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    """Describe the service without implying that screening is implemented."""

    return {
        "name": "Eligibility-Aware Clinical Trial Retrieval",
        "environment": settings.app_env,
        "status": "foundation scaffold",
        "safety": "Synthetic patient cases only; not medical advice.",
    }
