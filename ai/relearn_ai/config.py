import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo-root .env, resolved from this file — loads no matter the process CWD
# (services run from ai/ and backend/). Real env vars still take precedence.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _export_dotenv(path: Path) -> None:
    """Populate os.environ from .env. pydantic-settings reads .env into the
    Settings object only; the model registry's api_key lookup reads os.environ
    directly (registry.py), so without this the worker/agent never see
    GEMINI_API_KEY etc. unless exported in the shell. Real env vars win."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_export_dotenv(_ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    database_url: str = "postgresql+asyncpg://relearn:relearn@localhost:5432/relearn"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "relearn"
    s3_access_key: str = "relearn"
    s3_secret_key: str = "relearn-dev"

    ai_service_port: int = 8001
    internal_token: str = "dev-internal-token"

    datalab_api_key: str = ""
    # absolute path: durable host-filesystem mirror of pdfs/parses/images.
    # written alongside S3 on every put; read as a fallback when S3 misses, so
    # re-ingestion stays free (no Datalab re-parse) even if MinIO is wiped.
    local_cache_dir: str = ""
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
