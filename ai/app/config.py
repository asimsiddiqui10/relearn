from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://relearn:relearn@localhost:5432/relearn"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "relearn"
    s3_access_key: str = "relearn"
    s3_secret_key: str = "relearn-dev"

    ai_service_port: int = 8001
    internal_token: str = "dev-internal-token"

    datalab_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    anthropic_api_key: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # test seam: deterministic embeddings without the BGE-M3 download
    embeddings_fake: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
