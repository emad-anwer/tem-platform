from enum import StrEnum
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    app_name: str = "tem-platform"
    environment: str = "dev"
    log_level: str = "INFO"

    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://user:pass@localhost:5432/db"
    )
    # RedisDsn validates the URL format at startup (Settings load time)
    # instead of failing later at runtime when a connection is first attempted.
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    postgres_user: str = "tem_user"
    postgres_password: str = ""
    postgres_db: str = "tem_platform"
    db_port: int = 5432

    # Redis connection tuning
    redis_max_retries: int = 3
    redis_retry_base_delay: float = 1.0
    redis_socket_connect_timeout: float = 5.0
    redis_socket_timeout: float = 5.0
    redis_health_cache_ttl: int = 5

    # In production, set REDIS_REQUIRED=true to fail startup if Redis is unreachable.
    # In dev, Redis failure is tolerated — the app runs without cache/queue.
    redis_required: bool = False

    problem_base_url: str = "https://tem-platform.dev/problems"

    # W4-02 (issue #94): the scan scope allowlist — comma-separated entries of
    # hostnames, IPs, CIDRs, and `host:port` loopback pairs (see
    # `app.core.scope`). Default deny: empty scans nothing. Configuration,
    # not per-tenant data — per-tenant scope is week 6.
    scan_scope_allowlist: str = ""

    # W4-09 (issue #101): scheduler knobs for the two arq cron jobs.
    # Sweep marks worker-killed runs stale; the scan tick re-enqueues one
    # job per active target. The per-tick cap bounds the fan-out so 200
    # targets don't become a self-inflicted outage (W4-05's limiter is
    # per-host and won't save a cross-host fan-out).
    scheduled_sweep_interval_minutes: int = Field(default=5, ge=1, le=60)
    scheduled_scan_interval_minutes: int = Field(default=60, ge=5, le=1440)
    scheduled_scan_max_targets_per_tick: int = Field(default=50, ge=1, le=500)

    # Scanner egress is a shared target budget, enforced in Redis. Override
    # keys are ``host`` or ``operation:host`` (for example ``dns:resolver``).
    scan_rate_limit_default_per_second: int = Field(default=5, gt=0)
    scan_rate_limit_overrides: dict[str, int] = Field(default_factory=dict)
    scan_rate_limit_max_wait_seconds: float = Field(default=10.0, ge=0)

    # Fail-closed: FastAPI debug tracebacks leak source code and absolute
    # paths on unhandled errors (OWASP A05), so debug may only be enabled
    # explicitly via setting DEBUG=true. Default is False.
    debug: bool = False

    # Zitadel
    zitadel_issuer: str = "http://zitadel:8080"
    zitadel_project_id: str = ""

    zitadel_management_client_id: str = ""
    zitadel_management_client_secret: str = ""
    zitadel_http_timeout_seconds: float = 5.0

    # Dev-only bootstrap credential per ADR-0002 ("POST /tenants — closing the
    # open door"): lets the very first tenant be created before any Zitadel
    # org/user exists to hold platform_admin. A static secret, not a JWT.
    # Empty by default (disabled); only ever honored when environment == "dev".
    bootstrap_admin_token: str = ""

    port_scan_concurrency: int = Field(default=50, ge=1, le=500)
    port_scan_connect_timeout_seconds: float = Field(default=1.5, gt=0, le=30)

    @property
    def oidc_discovery_url(self) -> str:
        return f"{self.zitadel_issuer}/.well-known/openid-configuration"


@lru_cache
def get_settings() -> Settings:
    return Settings()
