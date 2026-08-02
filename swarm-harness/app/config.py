# app/config.py
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    KIMI_API_KEY: str = os.getenv("KIMI_API_KEY", "")
    API_KEY: str = os.getenv("API_KEY", "dev-key-change-me")
    MAX_STEPS: int = int(os.getenv("MAX_STEPS", "25"))
    DEFAULT_TOKEN_BUDGET: int = int(os.getenv("DEFAULT_TOKEN_BUDGET", "50000"))
    NOTIFICATION_WEBHOOK: str = os.getenv("NOTIFICATION_WEBHOOK", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    # Model used when a "kimi" agent runs without KIMI_API_KEY set
    DEEPSEEK_FALLBACK_MODEL: str = os.getenv("DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-flash-ultra-reasoning")

CONFIG = Config()
