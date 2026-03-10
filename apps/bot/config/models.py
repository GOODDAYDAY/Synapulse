"""YAML model configuration loader — parse, validate, and expand env vars.

Loads config/models.yaml which defines multiple AI endpoints with tags,
priority, and enabled flags. Supports ${ENV_VAR} expansion for secrets.
Falls back to legacy .env config when models.yaml is absent.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import logging

logger = logging.getLogger("synapulse.config.models")

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")
_VALID_PROTOCOLS = {"openai", "anthropic"}


class ConfigError(Exception):
    """Raised when models.yaml has invalid format or missing fields."""


@dataclass(frozen=True)
class EndpointConfig:
    """Immutable configuration for a single AI endpoint."""

    name: str
    protocol: str
    base_url: str
    api_key: str
    model: str
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 0


def load_models_config(path: str) -> list[EndpointConfig]:
    """Load and validate models.yaml. Raises ConfigError on invalid format.

    Each endpoint's api_key field supports ${ENV_VAR} expansion.
    Missing env vars produce a WARNING and the key is set to empty string.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Models config not found: {path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e

    if not raw or not isinstance(raw, dict):
        raise ConfigError(f"models.yaml must be a YAML mapping, got: {type(raw).__name__}")

    raw_models = raw.get("models")
    if not raw_models or not isinstance(raw_models, list):
        raise ConfigError("models.yaml must contain a 'models' list with at least one endpoint")

    endpoints = []
    seen_names: set[str] = set()
    for i, entry in enumerate(raw_models):
        ep = _validate_endpoint(entry, i)
        if ep.name in seen_names:
            raise ConfigError(f"Duplicate endpoint name '{ep.name}' at index {i}")
        seen_names.add(ep.name)
        endpoints.append(ep)

    logger.info("Loaded %d endpoint(s) from %s", len(endpoints), path)
    return endpoints


def build_legacy_endpoint(provider: str, model: str) -> list[EndpointConfig]:
    """Build a single-endpoint config from legacy AI_PROVIDER + AI_MODEL .env settings.

    Returns empty list for 'mock' provider (mock handles itself).
    """
    if provider == "mock":
        return []

    if provider == "copilot":
        api_key = os.getenv("GITHUB_TOKEN", "")
        if not api_key:
            logger.warning("GITHUB_TOKEN not set for legacy copilot provider")
        return [EndpointConfig(
            name="legacy-copilot",
            protocol="openai",
            base_url="https://models.inference.ai.azure.com",
            api_key=api_key,
            model=model,
            tags=["default"],
        )]

    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return [EndpointConfig(
            name="legacy-ollama",
            protocol="openai",
            base_url=f"{base_url}/v1",
            api_key="",
            model=model,
            tags=["default"],
        )]

    logger.warning("Unknown legacy provider '%s', no endpoints created", provider)
    return []


def _validate_endpoint(raw: dict, index: int) -> EndpointConfig:
    """Validate a single endpoint entry and return typed config."""
    if not isinstance(raw, dict):
        raise ConfigError(f"Endpoint at index {index} must be a mapping, got: {type(raw).__name__}")

    # Check required fields (tags checked separately for empty-list case)
    missing = [f for f in ("name", "protocol", "base_url", "model") if not raw.get(f)]
    if "tags" not in raw:
        missing.append("tags")
    if missing:
        raise ConfigError(f"Endpoint at index {index} missing required fields: {', '.join(missing)}")

    name = str(raw["name"])
    protocol = str(raw["protocol"]).lower()
    if protocol not in _VALID_PROTOCOLS:
        raise ConfigError(
            f"Endpoint '{name}' has invalid protocol '{protocol}', must be one of: {_VALID_PROTOCOLS}"
        )

    tags = raw["tags"]
    if not isinstance(tags, list) or not tags:
        raise ConfigError(f"Endpoint '{name}' must have a non-empty 'tags' list")
    tags = [str(t) for t in tags]

    # Expand env vars in api_key
    api_key = _expand_env_vars(str(raw.get("api_key", "")), name)

    return EndpointConfig(
        name=name,
        protocol=protocol,
        base_url=str(raw["base_url"]).rstrip("/"),
        api_key=api_key,
        model=str(raw["model"]),
        tags=tags,
        enabled=bool(raw.get("enabled", True)),
        priority=int(raw.get("priority", 0)),
    )


def _expand_env_vars(value: str, endpoint_name: str) -> str:
    """Replace ${VAR} with os.environ value. Warn and return empty on missing var."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            logger.warning(
                "Endpoint '%s': env var '%s' not found, api_key will be empty",
                endpoint_name, var_name,
            )
            return ""
        return env_value

    return _ENV_VAR_PATTERN.sub(_replace, value)
