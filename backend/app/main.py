"""Local FastAPI research application; dependencies are initialized lazily."""

import threading
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from backend.app.api.boundary import LocalBoundary, error
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.research import router as research_router
from backend.app.core.config import get_settings
from backend.app.core.errors import ServiceError


def create_app(*, service=None, settings=None):
    @asynccontextmanager
    async def lifespan(app):
        yield
        if app.state.engine is not None:
            app.state.engine.dispose()

    app = FastAPI(
        title="Eligibility-Aware Clinical Trial Retrieval API",
        version="0.2.0",
        description="Local API for verified synthetic cases only. Relevance, deterministic "
        "screening and learned advisories remain separate. Not confirmed medical eligibility.",
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()
    app.state.service = service
    app.state.engine = None
    app.state.initialization_lock = threading.Lock()
    app.add_middleware(LocalBoundary)
    app.include_router(health_router)
    app.include_router(research_router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc):
        # FastAPI's default includes submitted input values. Never echo them here.
        return error(
            422, "invalid_request", "Request does not match the documented schema or bounds."
        )

    @app.exception_handler(ServiceError)
    async def domain_error(request: Request, exc):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc):
        return error(exc.status_code, "http_error", "The requested route or method is unavailable.")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc):
        # Fixed messages prevent SQL parameters, DSNs, paths and submitted values leaking.
        if isinstance(exc, ImportError):
            return error(
                503, "dependency_unavailable", "A required local dependency is unavailable."
            )
        from sqlalchemy.exc import SQLAlchemyError

        from backend.app.repositories.postgres import ConflictError, EvidenceError

        if isinstance(exc, ConflictError):
            return error(
                409, "immutable_conflict", "Stored immutable evidence differs from this operation."
            )
        if isinstance(exc, EvidenceError | ValueError):
            return error(
                409,
                "evidence_mismatch",
                "Evidence or version validation failed; no result accepted.",
            )
        if isinstance(exc, SQLAlchemyError | httpx.HTTPError | OSError):
            return error(
                503, "dependency_unavailable", "A local service, artifact or model is unavailable."
            )
        return error(500, "internal_error", "The operation failed; no result was accepted.")

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": "Eligibility-Aware Clinical Trial Retrieval",
            "environment": app.state.settings.app_env,
            "status": "bounded research API",
            "safety": "Verified synthetic cases only; not medical advice.",
        }

    return app


app = create_app()
