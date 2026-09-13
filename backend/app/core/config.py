"""Environment-based application settings.

All configuration comes from environment variables (optionally loaded from a
local .env file for development). Nothing client-specific is hardcoded here:
per-deployment differences (which client, which modules are enabled, which
API token, which database) all flow in through the environment so the same
codebase/image can be deployed for any client instance.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # General
    app_name: str = "AutoService Platform API"
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str
    # Optional override used only by the test suite; falls back to
    # `database_url` with a `_test` suffix when not provided.
    test_database_url: str | None = None

    # Integration API
    api_token: str

    # CORS - comma separated list of allowed origins
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
