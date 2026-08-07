# tests/test_config.py — production environment validation (issue #5)
#
# Production mode (ENVIRONMENT=production, or any Railway deploy) must refuse
# to start with insecure/missing configuration: the dev default APP_API_KEY,
# no REDIS_URL, or no LLM provider key are all hard startup errors. Local
# development keeps the lenient defaults.
import importlib
import pytest

import app.config as config_module
from app.config import CONFIG, DEV_API_KEY


def _clear_keys(monkeypatch):
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)


def _clear_prod_required(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)


# --- development mode keeps the lenient defaults (backward compat) ----------

def test_development_defaults_still_load(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    _clear_keys(monkeypatch)
    _clear_prod_required(monkeypatch)
    assert config_module._is_production() is False
    # _production_problems() reports unconditionally; only production boots
    # are blocked on them — development stays lenient (backward compat).
    assert config_module._fail_fast_on_production_misconfiguration() is None
    assert CONFIG.API_KEY == DEV_API_KEY  # dev default still fine locally


# --- production detection ----------------------------------------------------

def test_production_detection_via_environment_var(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    assert config_module._is_production() is True


def test_production_detection_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "Production")
    assert config_module._is_production() is True


def test_production_detection_via_railway_environment(monkeypatch):
    # Railway sets RAILWAY_ENVIRONMENT on every deploy (usually "production");
    # a Railway box is never local dev, so it must validate like production.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert config_module._is_production() is True


# --- production validation rules ---------------------------------------------

def test_production_rejects_dev_api_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    _clear_keys(monkeypatch)  # no key -> falls back to the dev default
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
    problems = config_module._production_problems()
    assert any("APP_API_KEY" in p and DEV_API_KEY in p for p in problems)


def test_production_rejects_explicit_dev_api_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_API_KEY", DEV_API_KEY)
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
    problems = config_module._production_problems()
    assert any("APP_API_KEY" in p for p in problems)


def test_production_accepts_real_api_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_API_KEY", "sk-real-secret")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
    assert config_module._production_problems() == []


def test_production_requires_redis_url(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_API_KEY", "sk-real-secret")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
    problems = config_module._production_problems()
    assert any("REDIS_URL" in p for p in problems)


def test_production_requires_an_llm_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_API_KEY", "sk-real-secret")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    _clear_prod_required(monkeypatch)
    problems = config_module._production_problems()
    assert any("DEEPSEEK_API_KEY" in p and "KIMI_API_KEY" in p for p in problems)


def test_production_accepts_kimi_only(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_API_KEY", "sk-real-secret")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("KIMI_API_KEY", "sk-kimi")
    assert config_module._production_problems() == []


def test_production_accepts_legacy_api_key_name(monkeypatch):
    # API_KEY is the backward-compatible alias; a real value must pass too.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "sk-legacy-secret")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real")
    assert config_module._production_problems() == []


# --- integration: importing the module fails fast in a broken prod env -------

def test_import_fails_fast_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_API_KEY", "sk-real-secret")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    _clear_prod_required(monkeypatch)
    try:
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            importlib.reload(config_module)
    finally:
        # Always restore a clean development environment for the rest of the
        # suite, even if the assertion above fails.
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
        _clear_keys(monkeypatch)
        _clear_prod_required(monkeypatch)
        importlib.reload(config_module)
    assert config_module.CONFIG.PRODUCTION_MODE is False
    assert config_module.CONFIG.API_KEY == DEV_API_KEY
