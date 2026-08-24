from functools import lru_cache
from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn


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
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO

    database_url: PostgresDsn

    @property
    def debug(self) -> bool:
        return self.environment is not Environment.PROD


@lru_cache()
def get_settings() -> Settings:
    return Settings()
