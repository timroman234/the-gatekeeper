"""Application settings loaded from environment / .env file."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str
    anthropic_api_key: str = ""  # reserved for future Claude migration
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = True
    langchain_project: str = "the-gatekeeper"
    gmail_credentials_path: Path = Path("credentials.json")
    gmail_token_path: Path = Path("token.json")
    db_path: Path = Path("data/gatekeeper.db")
    checkpoint_path: Path = Path("data/checkpoints.db")
    email_max_results: int = 10


settings = Settings()
