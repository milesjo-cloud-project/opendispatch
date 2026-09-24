from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from environment variables (.env locally, Secret Manager on GCP later)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql://opendispatch:change-me@localhost:5432/opendispatch"


settings = Settings()
