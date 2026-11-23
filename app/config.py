from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env.dev supplies non-secret local-dev defaults; .env (gitignored) overrides it when present.
    model_config = SettingsConfigDict(
        env_file=(".env.dev", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    server_host: str = "0.0.0.0"
    server_port: int = 8000

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/measurement_backend"

    environment: str = "production"

    secret_key: str = "SECRET_KEY_FOR_JWT_TOKENS_CHANGE_IN_PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Most distinct measurement ids one `POST /measurements/export-selection` may reference.
    selection_export_max_ids: int = 50_000

    # Push notifications go out through ntfy. Never settable per request.
    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_access_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Get application settings, sourced from the process environment, `.env`, and `.env.dev`."""
    return Settings()
