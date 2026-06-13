from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo-root .env, resolved from this file — loads no matter the process CWD
# (services run from ai/ and backend/). Real env vars still take precedence.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    database_url: str = "postgresql+asyncpg://relearn:relearn@localhost:5432/relearn"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "relearn"
    s3_access_key: str = "relearn"
    s3_secret_key: str = "relearn-dev"
    # absolute path: durable host-filesystem mirror of raw PDFs (see ai/storage)
    local_cache_dir: str = ""

    backend_port: int = 8000
    ai_service_url: str = "http://localhost:8001"
    internal_token: str = "dev-internal-token"

    # auth: 'dev' issues local HS256 JWTs (no AWS); 'oidc' verifies via JWKS (Cognito)
    auth_mode: str = "dev"
    auth_dev_secret: str = "dev-jwt-secret-change-me"
    oidc_issuer: str = ""
    oidc_audience: str = ""

    # presigned URL TTL for PDFs served to the visualizer
    signed_url_ttl_s: int = 3600

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
