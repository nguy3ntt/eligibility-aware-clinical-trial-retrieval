"""Local research routes over catalog IDs; no arbitrary patient narrative uploads."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.core.errors import ServiceError
from backend.app.schemas.api import (
    ErrorResponse,
    ExperimentRequest,
    OperationResponse,
    ScreeningRequest,
    ScreeningResponse,
    SearchRequest,
    SearchResponse,
    TrialResponse,
)
from backend.app.schemas.patient import PatientProfile

router = APIRouter(
    prefix="/v1",
    responses={status: {"model": ErrorResponse} for status in (404, 409, 413, 422, 429, 500, 503)},
)


def service(request: Request):
    app = request.app
    if app.state.service is None:
        with app.state.initialization_lock:
            if app.state.service is None:
                from backend.app.repositories.postgres import PostgresStore, local_engine
                from backend.app.services.application import ResearchService

                config = app.state.settings
                app.state.engine = local_engine(config.database_url)
                app.state.service = ResearchService(
                    PostgresStore(app.state.engine, config.api_catalog_id), config
                )
    return app.state.service


Service = Annotated[object, Depends(service)]
CaseID = Annotated[str, Path(pattern=r"^[A-Za-z0-9:_-]{1,120}$")]
TrialID = Annotated[str, Path(pattern=r"^NCT[0-9]{8}$")]
OperationID = Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]
Limit = Annotated[int, Query(ge=1, le=50)]
Offset = Annotated[int, Query(ge=0, le=10000)]


@router.get("/ready", tags=["health"])
def ready(api: Service) -> dict:
    return api.readiness()


@router.get("/cases", tags=["cases"])
def cases(api: Service, limit: Limit = 20, offset: Offset = 0) -> dict:
    return api.page("cases", limit, offset)


@router.get("/cases/{case_id}", tags=["cases"], response_model=PatientProfile)
def case(case_id: CaseID, api: Service) -> dict:
    from backend.app.schemas.patient import SyntheticCase
    from backend.app.services.patient_extraction.extractor import extract_profile

    return extract_profile(SyntheticCase.model_validate(api.record("cases", case_id))).model_dump(
        mode="json"
    )


@router.get("/trials", tags=["trials"])
def trials(api: Service, limit: Limit = 20, offset: Offset = 0) -> dict:
    return api.page("trials", limit, offset)


@router.get("/trials/{trial_id}", tags=["trials"], response_model=TrialResponse)
def trial(trial_id: TrialID, api: Service) -> dict:
    from pipelines.criteria.parser import parse_eligibility
    from pipelines.reranking_data import eligibility_source

    record = api.record("trials", trial_id)
    return {
        "evidence": record,
        "criteria": parse_eligibility(eligibility_source(record)).model_dump(mode="json"),
    }


@router.post("/search", tags=["search"], response_model=SearchResponse)
def search(body: SearchRequest, api: Service):
    return api.execute("search", body)


@router.post("/screening", tags=["screening"], response_model=ScreeningResponse)
def screening(body: ScreeningRequest, api: Service):
    return api.execute("screening", body)


@router.post("/experiments", tags=["experiments"], response_model=OperationResponse)
def run_experiment(body: ExperimentRequest, api: Service):
    """Run only the fixed, bounded invented screening evaluation; no arbitrary jobs or paths."""
    return api.execute("experiment", body)


@router.get("/experiments", tags=["experiments"])
def experiments(api: Service, limit: Limit = 20, offset: Offset = 0) -> dict:
    """List persisted API runs and explicitly imported historical experiment manifests."""
    return api.page("operations", limit, offset)


@router.get("/experiments/{operation_id}", tags=["experiments"])
def experiment(operation_id: OperationID, api: Service) -> dict:
    result = api.store.get("operations", operation_id)
    if result is None:
        raise ServiceError(404, "not_found", "The requested experiment record does not exist.")
    return result
