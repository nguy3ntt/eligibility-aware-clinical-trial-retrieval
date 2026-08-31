"""Environment-backed application configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validate configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
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


@lru_cache
def get_settings() -> Settings:
    """Create one validated settings object per process."""

    return Settings()


settings = get_settings()
