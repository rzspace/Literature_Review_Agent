from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    app_password: str = ""

    openalex_api_key: str = ""
    openalex_email: str = ""
    unpaywall_email: str = ""
    crossref_email: str = ""

    database_url: str = "sqlite:///data/app.db"
    data_dir: str = "data"

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def data_path(self) -> Path:
        return ROOT_DIR / self.data_dir

    @property
    def database_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            relative_path = self.database_url.removeprefix("sqlite:///")
            return ROOT_DIR / relative_path
        raise ValueError("第 1 版仅支持 sqlite:///... 数据库地址")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    (settings.data_path / "pdfs").mkdir(parents=True, exist_ok=True)
    (settings.data_path / "exports").mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings

