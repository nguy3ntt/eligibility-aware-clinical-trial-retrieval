"""Environment-backed application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validate configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=(".env", ".env.api.local"), extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+psycopg://clinical_trial_retrieval:change-me-locally"
        "@localhost:5432/clinical_trial_retrieval"
    )
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    clinical_trials_api_base_url: str = "https://clinicaltrials.gov/api/v2"
    raw_data_dir: str = "data/raw"
    interim_data_dir: str = "data/interim"
    processed_data_dir: str = "data/processed"
    api_catalog_id: str = "bounded-api-v1"
    api_index_id: str = "dense-m3-minilm-v1"
    api_evidence_id: str = "reranking-evidence-v1"
    api_collection: str = "trials_hybrid_v1"


@lru_cache
def get_settings() -> Settings:
    """Create one validated settings object per process."""

    return Settings()


settings = get_settings()
