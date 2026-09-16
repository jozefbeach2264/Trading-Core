"""Grok → local: no xAI key requirement, local llama-server is the default provider."""
import os

from config.config import Config


def test_live_mode_does_not_require_an_ai_api_key(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "False")
    monkeypatch.setenv("ASTERDEX_API_KEY", "k")
    monkeypatch.setenv("ASTERDEX_API_SECRET", "s")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("XAI_API_KEY", "")
    cfg = Config()
    assert cfg.dry_run_mode is False
    assert not cfg.ai_api_key


def test_default_provider_is_the_local_llama_server(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    cfg = Config()
    assert cfg.ai_provider_url == "http://127.0.0.1:8081/v1"
    assert cfg.ai_model == "local"
    assert cfg.ai_disable_thinking is True
    assert cfg.ai_max_tokens > 0


def test_legacy_xai_key_still_honoured(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("XAI_API_KEY", "xai-legacy")
    assert Config().ai_api_key == "xai-legacy"


def test_trailing_slash_on_provider_url_is_stripped(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_URL", "http://127.0.0.1:8081/v1/")
    assert Config().ai_provider_url == "http://127.0.0.1:8081/v1"


def test_memory_db_path_is_configurable(config):
    assert config.memory_db_path == os.environ["MEMORY_DB_PATH"]


def test_compression_range_ratio_must_be_positive(monkeypatch):
    import pytest
    monkeypatch.setenv("COMPRESSION_RANGE_RATIO", "0")
    with pytest.raises(ValueError):
        Config()


def test_exchange_keepalive_must_be_positive(monkeypatch):
    import pytest
    monkeypatch.setenv("EXCHANGE_KEEPALIVE_SECONDS", "0")
    with pytest.raises(ValueError):
        Config()
