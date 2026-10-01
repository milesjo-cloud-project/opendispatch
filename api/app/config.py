from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from environment variables (.env locally, Secret Manager on GCP later)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql://opendispatch:change-me@127.0.0.1:5432/opendispatch"

    # SMS alerts. Leave unset and alerts go to the API log instead.
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None

    @property
    def sms_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"

    @model_validator(mode="after")
    def _require_database_url_outside_local(self) -> "Settings":
        # The default above is for local dev only; anywhere else a missing URL is a mistake.
        if not self.is_local and "database_url" not in self.model_fields_set:
            raise ValueError("DATABASE_URL must be set when APP_ENV is not 'local'")
        return self


settings = Settings()
