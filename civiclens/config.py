from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///.data/civiclens.db"
    data_dir: Path = Path(".data")
    admin_token: SecretStr | None = None
    cors_origin: str = "http://localhost:3000"
    secure_cookies: bool = False
    max_pdf_bytes: int = Field(default=40_000_000, ge=1024)
    max_pdf_pages: int = Field(default=300, ge=1)
    ocr_min_chars: int = Field(default=30, ge=0)
    ocr_dpi: int = Field(default=200, ge=72, le=350)
    tessdata: str | None = None
    embedding_model: str | None = None
    llm_endpoint: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_endpoint and self.llm_model)


@lru_cache
def settings() -> Settings:
    return Settings()
