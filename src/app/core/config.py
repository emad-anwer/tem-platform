from enum import StrEnum
from functools import lru_cache

from pydantic import PostgresDsn
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
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    app_name: str = "tem-platform"
    environment: Environment = Environment.DEV
    log_level: LogLevel = LogLevel.INFO

    database_url: PostgresDsn
    redis_url: str = "redis://localhost:6379/0"

    postgres_user: str = "tem_user"
    postgres_password: str = ""
    postgres_db: str = "tem_platform"
    db_port: int = 5432
    redis_password: str = ""

    @property
    def debug(self) -> bool:
        return self.environment is not Environment.PROD


@lru_cache
def get_settings() -> Settings:
    return Settings()
