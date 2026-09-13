from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Runtime configuration. Secrets are supplied through environment variables only."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str | None = None
    # gemma2-9b-it is configurable for the assignment; it is currently retired by Groq.
    groq_model: str = "openai/gpt-oss-20b"
    database_url: str = "sqlite+aiosqlite:///./aivoa.db"
    frontend_origin: str = "http://localhost:5173"
    max_upload_bytes: int = 10 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
