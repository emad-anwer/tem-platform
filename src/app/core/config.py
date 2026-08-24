from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    app_name: str = "tem-platform"
    environment: str = "dev"
    debug: bool = False
    log_level: str = "INFO"

    database_url: PostgresDsn


@lru_cache()
def get_settings() -> Settings:
    return Settings()
