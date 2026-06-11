"""models.yaml loader — roles → model aliases → provider configs (spec/06)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

MODELS_YAML = Path(__file__).resolve().parents[2] / "models.yaml"


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    provider: str  # openai_compat | local_embeddings
    model_id: str
    base_url: str | None = None
    api_key_env: str | None = None
    capabilities: dict = field(default_factory=dict)
    context_window: int | None = None
    dim: int | None = None

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None


@dataclass(frozen=True)
class RoleConfig:
    primary: str
    fallback: str | None = None


class Registry:
    def __init__(self, raw: dict):
        self.roles: dict[str, RoleConfig] = {
            name: RoleConfig(primary=cfg["primary"], fallback=cfg.get("fallback"))
            for name, cfg in (raw.get("roles") or {}).items()
        }
        self.models: dict[str, ModelConfig] = {
            alias: ModelConfig(
                alias=alias,
                provider=cfg["provider"],
                model_id=cfg["model_id"],
                base_url=cfg.get("base_url"),
                api_key_env=cfg.get("api_key_env"),
                capabilities=cfg.get("capabilities") or {},
                context_window=cfg.get("context_window"),
                dim=cfg.get("dim"),
            )
            for alias, cfg in (raw.get("models") or {}).items()
        }

    def resolve(self, role: str, model_alias: str | None = None) -> ModelConfig:
        alias = model_alias
        if alias is None:
            role_cfg = self.roles.get(role)
            if role_cfg is None:
                raise KeyError(f"unknown llm role {role!r} (roles: {list(self.roles)})")
            alias = role_cfg.primary
        model = self.models.get(alias)
        if model is None:
            raise KeyError(f"unknown model alias {alias!r} (models: {list(self.models)})")
        return model

    def fallback_for(self, role: str) -> ModelConfig | None:
        role_cfg = self.roles.get(role)
        if role_cfg and role_cfg.fallback:
            return self.models.get(role_cfg.fallback)
        return None


@lru_cache
def get_registry() -> Registry:
    with open(MODELS_YAML) as f:
        return Registry(yaml.safe_load(f))
