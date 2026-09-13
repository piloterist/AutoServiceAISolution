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

    # Optional module: Yandex.Disk relay.
    #
    # Fallback ingestion path for environments where 1C's outbound network is
    # firewalled against reaching this backend directly (seen with the
    # Pan Motors / 5Systems hosting: outbound HTTPS to arbitrary "cloud
    # hosting" IP ranges is blocked, but general internet - including
    # Yandex's own infrastructure - is not). When enabled, 1C uploads its
    # export JSON to a folder on Yandex.Disk via WebDAV instead of calling
    # this API directly; this backend polls that folder, imports any new
    # file through the exact same `process_work_order_import` path as the
    # direct API, and moves the file to a "processed" subfolder. Disabled by
    # default - a client whose network reaches this backend directly never
    # needs it.
    enable_yandex_relay: bool = False
    yandex_disk_oauth_token: str | None = None
    yandex_disk_watch_path: str = "/1c-export"
    yandex_poll_interval_seconds: int = 300

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
