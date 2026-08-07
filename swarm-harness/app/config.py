# app/config.py
import os
from dataclasses import dataclass, field

# The well-known development default. Production mode refuses to start with it
# (see _fail_fast_on_production_misconfiguration) — it must never protect a
# public deployment.
DEV_API_KEY = "dev-key-change-me"

def _api_keys_tuple() -> tuple:
    """Comma-separated list of accepted API keys.

    Prefers APP_API_KEY; falls back to the legacy API_KEY name. A single
    key still works — just don't put a comma in it.
    """
    raw = os.getenv("APP_API_KEY") or os.getenv("API_KEY", DEV_API_KEY)
    return tuple(k.strip() for k in raw.split(",") if k.strip())

def _is_production() -> bool:
    """True when the app must behave as a production deployment.

    Set explicitly via ENVIRONMENT=production, or detected on managed
    platforms: Railway sets RAILWAY_ENVIRONMENT on every deployment (the
    environment name, usually "production"), so a Railway box can never
    silently boot with development defaults.
    """
    if os.getenv("ENVIRONMENT", "").strip().lower() == "production":
        return True
    return bool(os.getenv("RAILWAY_ENVIRONMENT"))

def _production_problems() -> list:
    """Configuration problems that must block startup in production.

    Returns [] when the environment is production-safe. Checks are about
    presence/security only (never connectivity — health must not depend on
    Redis being up).
    """
    problems = []
    keys = _api_keys_tuple()
    if not keys:
        problems.append("APP_API_KEY: no API key configured — set APP_API_KEY to a real secret")
    elif any(k == DEV_API_KEY for k in keys):
        problems.append(
            f"APP_API_KEY: must not be the development default '{DEV_API_KEY}' — "
            "that key is public knowledge and would let anyone submit builds"
        )
    if not os.getenv("REDIS_URL"):
        problems.append(
            "REDIS_URL: must be set — the 'redis://localhost:6379' default only "
            "works for local development"
        )
    if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("KIMI_API_KEY")):
        problems.append(
            "DEEPSEEK_API_KEY and/or KIMI_API_KEY: at least one LLM provider key "
            "is required (no agent can run without one)"
        )
    return problems

def _fail_fast_on_production_misconfiguration():
    """Refuse to boot in production with insecure or missing configuration.

    Fails at import time so the container exits immediately with an
    actionable message instead of serving /v1/health while every build
    fails or — worse — accepting builds with a public default API key.
    """
    if not _is_production():
        return
    problems = _production_problems()
    if problems:
        raise RuntimeError(
            "Refusing to start in production with insecure or missing configuration.\n"
            "Fix these on the deployment:\n- " + "\n- ".join(problems)
        )

@dataclass(frozen=True)
class Config:
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    # "development" (default) or "production". Production refuses to start with
    # insecure/missing config (see _fail_fast_on_production_misconfiguration).
    # Railway deploys are auto-detected via RAILWAY_ENVIRONMENT.
    ENVIRONMENT: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development").strip().lower() or "development")
    PRODUCTION_MODE: bool = field(default_factory=_is_production)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    KIMI_API_KEY: str = os.getenv("KIMI_API_KEY", "")
    # Kimi/Moonshot API base. International keys work on api.moonshot.ai;
    # China-region keys need KIMI_API_BASE=https://api.moonshot.cn/v1
    KIMI_API_BASE: str = os.getenv("KIMI_API_BASE", "https://api.moonshot.ai/v1")
    # First accepted key (backward-compat for code that reads CONFIG.API_KEY).
    API_KEY: str = field(default_factory=lambda: _api_keys_tuple()[0])
    # All accepted keys (APP_API_KEY or API_KEY, comma-separated).
    API_KEYS: tuple = field(default_factory=_api_keys_tuple)
    MAX_STEPS: int = int(os.getenv("MAX_STEPS", "25"))
    DEFAULT_TOKEN_BUDGET: int = int(os.getenv("DEFAULT_TOKEN_BUDGET", "4000000"))
    # Durability worker: reset builds stuck in a running state after this many minutes.
    STALE_BUILD_TTL_MINUTES: int = int(os.getenv("STALE_BUILD_TTL_MINUTES", "15"))
    # Quotas (0 = unlimited). MAX_CONCURRENT_BUILDS caps in-flight (non-terminal) builds;
    # DAILY_TOKEN_BUDGET caps total token usage across builds created in the last 24h.
    MAX_CONCURRENT_BUILDS: int = int(os.getenv("MAX_CONCURRENT_BUILDS", "0"))
    DAILY_TOKEN_BUDGET: int = int(os.getenv("DAILY_TOKEN_BUDGET", "0"))
    # Max parallel LLM calls per provider (swarm steps run concurrently up to this).
    # 0 = unlimited.
    LLM_CONCURRENCY: int = int(os.getenv("LLM_CONCURRENCY", "4"))
    NOTIFICATION_WEBHOOK: str = os.getenv("NOTIFICATION_WEBHOOK", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # Model used when a "kimi" agent runs without KIMI_API_KEY set.
    # Default is the model known to work with the user's DeepSeek key;
    # override with DEEPSEEK_FALLBACK_MODEL for other tiers (e.g. ultra reasoning).
    DEEPSEEK_FALLBACK_MODEL: str = os.getenv("DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-flash")
    # Default models when a call doesn't specify one (router fallbacks).
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    KIMI_MODEL: str = os.getenv("KIMI_MODEL", "kimi-k3")
    # Preloaded GitHub PAT: builds that omit a token use this one (personal deployments).
    DEFAULT_GITHUB_TOKEN: str = os.getenv("DEFAULT_GITHUB_TOKEN", "")
    # Cap for step outputs embedded in review/merge prompts (long outputs slow kimi
    # reviewers dramatically). Truncated text is marked so reviewers can flag cuts.
    REVIEW_PROMPT_MAX_CHARS: int = int(os.getenv("REVIEW_PROMPT_MAX_CHARS", "12000"))

CONFIG = Config()
_fail_fast_on_production_misconfiguration()
