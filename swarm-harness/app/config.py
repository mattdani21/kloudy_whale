# app/config.py
import os
from dataclasses import dataclass, field

def _api_keys_tuple() -> tuple:
    """Comma-separated list of accepted API keys.

    Prefers APP_API_KEY; falls back to the legacy API_KEY name. A single
    key still works — just don't put a comma in it.
    """
    raw = os.getenv("APP_API_KEY") or os.getenv("API_KEY", "dev-key-change-me")
    return tuple(k.strip() for k in raw.split(",") if k.strip())

@dataclass(frozen=True)
class Config:
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
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

CONFIG = Config()
