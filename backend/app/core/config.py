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

    # Optional module: live 5Systems (Alpha-Auto) lookup by vehicle plate.
    #
    # The nightly 1C export (see 1c/TestExportOrders.bsl, now a once-daily
    # job rather than every 30 minutes - see DEPLOYMENT.md) only reaches
    # today's newly-created work orders the following morning. This gives
    # the Planner a way to look one up immediately when an operator is
    # scheduling a car whose ЗН was just created in Alpha-Auto: a plate
    # search against 5Systems' own REST API (api.5systems.ru), which is
    # unrelated to the 1C export path entirely - see
    # services/fivesystems_client.py for the full flow and why it only
    # writes a *stub* WorkOrder row (never overwrites one the real import
    # already populated). Disabled by default - this is a Pan Motors/
    # 5Systems-specific integration, not something every client has.
    enable_fivesystems_lookup: bool = False
    fivesystems_api_base_url: str = "https://api.5systems.ru"
    fivesystems_username: str | None = None
    fivesystems_password: str | None = None
    fivesystems_company_uuid: str | None = None

    # Which work order status value(s) count as "revenue" for the dashboard's
    # reporting endpoints (monthly summary, by-department summary) - comma
    # separated, e.g. "Закрыт". A work order in any other status (open, in
    # progress, ...) still exists and is visible on the work orders list, it
    # just isn't counted as earned revenue yet. Left empty by default (no
    # restriction) since the actual status string is client-specific data,
    # not something the core should hardcode - see ARCHITECTURE.md.
    revenue_statuses: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def revenue_statuses_list(self) -> list[str]:
        return [status.strip() for status in self.revenue_statuses.split(",") if status.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
