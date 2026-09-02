from enum import StrEnum
from functools import lru_cache

from pydantic import PostgresDsn, RedisDsn
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

    # Fail-closed: FastAPI debug tracebacks leak source code and absolute
    # paths on unhandled errors (OWASP A05), so debug may only be enabled
    # explicitly via setting DEBUG=true. Default is False.
    debug: bool = False

    # Zitadel 
    zitadel_issuer: str = "http://zitadel:8080"
    zitadel_project_id: str = ""

    @property
    def oidc_discovery_url(self) -> str:
        return f"{self.zitadel_issuer}/.well-known/openid-configuration"

        


@lru_cache
def get_settings() -> Settings:
    return Settings()
