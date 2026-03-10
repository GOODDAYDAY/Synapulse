"""Tests for REQ-006 multi-model rotation — config loading, endpoint pool, and provider rotation."""

import os
import tempfile
import time

import pytest

from apps.bot.config.models import (
    ConfigError,
    EndpointConfig,
    build_legacy_endpoint,
    load_models_config,
)
from apps.bot.provider.endpoint import EndpointPool
from apps.bot.provider.errors import EndpointError, RateLimitError


# ====================================================================
# Module 4.1: config/models.py tests
# ====================================================================

class TestLoadModelsConfig:
    """AC-01, AC-02: YAML loading and validation."""

    def _write_yaml(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_load_valid_config(self):
        """AC-01: Load 3 endpoints successfully."""
        path = self._write_yaml("""
models:
  - name: ep1
    protocol: openai
    base_url: https://api.example.com
    api_key: test-key
    model: gpt-4o
    tags: [large, default]
  - name: ep2
    protocol: openai
    base_url: https://api2.example.com
    model: gpt-4o-mini
    tags: [small]
    enabled: true
    priority: 5
  - name: ep3
    protocol: openai
    base_url: http://localhost:11434/v1
    model: llama3
    tags: [large]
    enabled: false
""")
        endpoints = load_models_config(path)
        assert len(endpoints) == 3
        assert endpoints[0].name == "ep1"
        assert endpoints[0].api_key == "test-key"
        assert endpoints[1].priority == 5
        assert endpoints[2].enabled is False
        os.unlink(path)

    def test_missing_required_field(self):
        """AC-02: Missing protocol field."""
        path = self._write_yaml("""
models:
  - name: bad
    base_url: https://api.example.com
    model: gpt-4o
    tags: [default]
""")
        with pytest.raises(ConfigError, match="missing required fields.*protocol"):
            load_models_config(path)
        os.unlink(path)

    def test_invalid_protocol(self):
        path = self._write_yaml("""
models:
  - name: bad
    protocol: gemini
    base_url: https://api.example.com
    model: gpt-4o
    tags: [default]
""")
        with pytest.raises(ConfigError, match="invalid protocol"):
            load_models_config(path)
        os.unlink(path)

    def test_duplicate_name(self):
        path = self._write_yaml("""
models:
  - name: dup
    protocol: openai
    base_url: https://api.example.com
    model: gpt-4o
    tags: [default]
  - name: dup
    protocol: openai
    base_url: https://api2.example.com
    model: gpt-4o-mini
    tags: [small]
""")
        with pytest.raises(ConfigError, match="Duplicate endpoint name"):
            load_models_config(path)
        os.unlink(path)

    def test_empty_tags(self):
        path = self._write_yaml("""
models:
  - name: bad
    protocol: openai
    base_url: https://api.example.com
    model: gpt-4o
    tags: []
""")
        with pytest.raises(ConfigError, match="non-empty"):
            load_models_config(path)
        os.unlink(path)

    def test_empty_file(self):
        path = self._write_yaml("")
        with pytest.raises(ConfigError):
            load_models_config(path)
        os.unlink(path)

    def test_no_models_key(self):
        path = self._write_yaml("something_else: true")
        with pytest.raises(ConfigError, match="models"):
            load_models_config(path)
        os.unlink(path)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_models_config("/nonexistent/models.yaml")

    def test_invalid_yaml(self):
        path = self._write_yaml("models: [{{invalid}}")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_models_config(path)
        os.unlink(path)

    def test_base_url_trailing_slash_stripped(self):
        path = self._write_yaml("""
models:
  - name: ep
    protocol: openai
    base_url: https://api.example.com/v1/
    model: gpt-4o
    tags: [default]
""")
        endpoints = load_models_config(path)
        assert not endpoints[0].base_url.endswith("/")
        os.unlink(path)


class TestEnvVarExpansion:
    """AC-08, AC-09: Environment variable expansion."""

    def _write_yaml(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_expand_existing_env_var(self, monkeypatch):
        """AC-08: ${GITHUB_TOKEN} is expanded."""
        monkeypatch.setenv("TEST_API_KEY_006", "secret123")
        path = self._write_yaml("""
models:
  - name: ep
    protocol: openai
    base_url: https://api.example.com
    api_key: ${TEST_API_KEY_006}
    model: gpt-4o
    tags: [default]
""")
        endpoints = load_models_config(path)
        assert endpoints[0].api_key == "secret123"
        os.unlink(path)

    def test_missing_env_var_warning(self):
        """AC-09: Missing env var does not crash, key becomes empty."""
        path = self._write_yaml("""
models:
  - name: ep
    protocol: openai
    base_url: https://api.example.com
    api_key: ${NONEXISTENT_VAR_12345}
    model: gpt-4o
    tags: [default]
""")
        endpoints = load_models_config(path)
        assert endpoints[0].api_key == ""
        os.unlink(path)

    def test_no_api_key_field(self):
        """Endpoints without api_key get empty string."""
        path = self._write_yaml("""
models:
  - name: ep
    protocol: openai
    base_url: http://localhost:11434/v1
    model: llama3
    tags: [default]
""")
        endpoints = load_models_config(path)
        assert endpoints[0].api_key == ""
        os.unlink(path)


class TestBuildLegacyEndpoint:
    """AC-13: Backward compatibility fallback."""

    def test_copilot_legacy(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        endpoints = build_legacy_endpoint("copilot", "gpt-4o")
        assert len(endpoints) == 1
        assert endpoints[0].protocol == "openai"
        assert "models.inference.ai.azure.com" in endpoints[0].base_url
        assert endpoints[0].api_key == "ghp_test123"

    def test_ollama_legacy(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://myhost:11434")
        endpoints = build_legacy_endpoint("ollama", "llama3")
        assert len(endpoints) == 1
        assert endpoints[0].base_url == "http://myhost:11434/v1"
        assert endpoints[0].api_key == ""

    def test_mock_returns_empty(self):
        endpoints = build_legacy_endpoint("mock", "any")
        assert endpoints == []

    def test_unknown_provider(self):
        endpoints = build_legacy_endpoint("unknown", "model")
        assert endpoints == []


# ====================================================================
# Module 4.2: provider/endpoint.py tests
# ====================================================================

def _ep(name: str, tags: list[str], priority: int = 0, enabled: bool = True) -> EndpointConfig:
    """Helper to create test endpoints."""
    return EndpointConfig(
        name=name, protocol="openai", base_url="https://test.com",
        api_key="key", model="gpt", tags=tags, enabled=enabled, priority=priority,
    )


class TestEndpointPool:
    """AC-03 through AC-07: Tag filtering, rotation, and cooldown."""

    def test_filter_by_tag(self):
        """AC-03: Only endpoints with matching tag are returned."""
        pool = EndpointPool([
            _ep("a", ["large"]),
            _ep("b", ["small"]),
            _ep("c", ["large", "coding"]),
        ])
        large = pool.get_available("large")
        assert {ep.name for ep in large} == {"a", "c"}

    def test_filter_excludes_disabled(self):
        """Disabled endpoints are excluded."""
        pool = EndpointPool([
            _ep("a", ["default"], enabled=True),
            _ep("b", ["default"], enabled=False),
        ])
        available = pool.get_available("default")
        assert len(available) == 1
        assert available[0].name == "a"

    def test_nonexistent_tag_returns_empty(self):
        """AC-04: No endpoints for tag returns empty list."""
        pool = EndpointPool([_ep("a", ["large"])])
        assert pool.get_available("nonexistent") == []

    def test_sorted_by_priority(self):
        """Lower priority number = higher priority."""
        pool = EndpointPool([
            _ep("low", ["default"], priority=10),
            _ep("high", ["default"], priority=0),
            _ep("mid", ["default"], priority=5),
        ])
        available = pool.get_available("default")
        assert [ep.name for ep in available] == ["high", "mid", "low"]

    def test_cooldown_excludes_endpoint(self):
        """AC-07: Cooldown endpoints are skipped."""
        pool = EndpointPool([
            _ep("a", ["default"]),
            _ep("b", ["default"]),
        ])
        pool.mark_cooldown("a", 60.0)
        available = pool.get_available("default")
        assert len(available) == 1
        assert available[0].name == "b"

    def test_cooldown_expires(self):
        """After cooldown period, endpoint is available again."""
        pool = EndpointPool([_ep("a", ["default"])])
        # Set cooldown that's already expired
        pool._cooldowns["a"] = time.monotonic() - 1
        available = pool.get_available("default")
        assert len(available) == 1

    def test_all_in_cooldown(self):
        """AC-06: All endpoints in cooldown returns empty."""
        pool = EndpointPool([
            _ep("a", ["default"]),
            _ep("b", ["default"]),
        ])
        pool.mark_cooldown("a", 60.0)
        pool.mark_cooldown("b", 60.0)
        assert pool.get_available("default") == []

    def test_advance_cursor_rotates(self):
        """Round-robin: cursor advances to try different endpoint first."""
        pool = EndpointPool([
            _ep("a", ["default"], priority=0),
            _ep("b", ["default"], priority=0),
            _ep("c", ["default"], priority=0),
        ])
        first = pool.get_available("default")
        assert first[0].name == "a"

        pool.advance_cursor("default")
        second = pool.get_available("default")
        assert second[0].name == "b"

        pool.advance_cursor("default")
        third = pool.get_available("default")
        assert third[0].name == "c"

    def test_single_endpoint_no_rotation(self):
        """Single endpoint: no rotation needed."""
        pool = EndpointPool([_ep("only", ["default"])])
        available = pool.get_available("default")
        assert len(available) == 1
        assert available[0].name == "only"

    def test_update_preserves_cooldowns(self):
        """AC-11: Hot-reload preserves cooldown for existing endpoints."""
        pool = EndpointPool([
            _ep("a", ["default"]),
            _ep("b", ["default"]),
        ])
        pool.mark_cooldown("a", 60.0)

        # Update: keep "a", replace "b" with "c"
        pool.update([
            _ep("a", ["default"]),
            _ep("c", ["default"]),
        ])

        # "a" should still be in cooldown
        available = pool.get_available("default")
        assert {ep.name for ep in available} == {"c"}

    def test_update_removes_old_cooldowns(self):
        """Cooldowns for removed endpoints are cleaned up."""
        pool = EndpointPool([_ep("a", ["default"])])
        pool.mark_cooldown("a", 60.0)
        pool.update([_ep("b", ["default"])])
        assert "a" not in pool._cooldowns

    def test_endpoint_count(self):
        pool = EndpointPool([_ep("a", ["x"]), _ep("b", ["y"])])
        assert pool.endpoint_count == 2

    def test_get_tag_summary(self):
        pool = EndpointPool([
            _ep("a", ["large", "default"]),
            _ep("b", ["small"]),
            _ep("c", ["large"], enabled=False),
        ])
        summary = pool.get_tag_summary()
        assert summary == {"large": 1, "default": 1, "small": 1}

    def test_empty_pool(self):
        pool = EndpointPool()
        assert pool.get_available("any") == []
        assert pool.endpoint_count == 0

    def test_multi_tag_endpoint(self):
        """Single endpoint with multiple tags appears in both filters."""
        pool = EndpointPool([_ep("multi", ["large", "coding"])])
        assert len(pool.get_available("large")) == 1
        assert len(pool.get_available("coding")) == 1
        assert pool.get_available("small") == []


# ====================================================================
# Module 4.3: provider/errors.py tests
# ====================================================================

class TestErrors:
    def test_rate_limit_error(self):
        e = RateLimitError(retry_after=30.0)
        assert e.retry_after == 30.0
        assert "30" in str(e)

    def test_rate_limit_default(self):
        e = RateLimitError()
        assert e.retry_after == 60.0

    def test_endpoint_error(self):
        e = EndpointError(status=500, message="Internal Server Error")
        assert e.status == 500
        assert "Internal Server Error" in str(e)

    def test_endpoint_error_default_message(self):
        e = EndpointError(status=401)
        assert "401" in str(e)


# ====================================================================
# Module 4.4: provider/base.py rotation tests
# ====================================================================

class TestOpenAIProviderRotation:
    """AC-05, AC-06, AC-10, AC-14: Rotation behavior via chat()."""

    @pytest.mark.asyncio
    async def test_no_pool_returns_error(self):
        """Provider without pool returns error ChatResponse."""
        from apps.bot.provider.base import OpenAIProvider
        provider = OpenAIProvider()
        response = await provider.chat([{"role": "user", "content": "hi"}])
        assert "No endpoint pool" in response.text

    @pytest.mark.asyncio
    async def test_no_endpoints_for_tag(self):
        """AC-04: No available endpoints for given tag."""
        from apps.bot.provider.base import OpenAIProvider
        provider = OpenAIProvider()
        provider._pool = EndpointPool([_ep("a", ["large"])])
        response = await provider.chat(
            [{"role": "user", "content": "hi"}], tag="nonexistent",
        )
        assert "No available endpoints" in response.text

    @pytest.mark.asyncio
    async def test_chat_signature_backward_compatible(self):
        """AC-10: chat(messages) works without tag parameter."""
        from apps.bot.provider.base import OpenAIProvider
        provider = OpenAIProvider()
        provider._pool = EndpointPool([_ep("a", ["default"])])
        provider._default_tag = "default"
        # Will fail at HTTP level but should not crash on signature
        response = await provider.chat([{"role": "user", "content": "hi"}])
        # Endpoint is unreachable, so all fail
        assert "All endpoints failed" in response.text
