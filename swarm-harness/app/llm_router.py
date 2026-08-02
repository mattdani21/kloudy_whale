# app/llm_router.py
import aiohttp
import asyncio
import logging
from typing import List, Dict, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import CONFIG

logger = logging.getLogger(__name__)

class LLMRouter:
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=120, connect=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_deepseek(self, messages: List[Dict], model: str = "deepseek-chat", max_tokens: int = 4000) -> Tuple[str, int]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": False
        }
        async with self._lock:
            async with self.session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {CONFIG.DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json=payload
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_kimi(self, messages: List[Dict], model: str = "kimi-k3", max_tokens: int = 4000) -> Tuple[str, int]:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": False
        }
        async with self._lock:
            async with self.session.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers={"Authorization": f"Bearer {CONFIG.KIMI_API_KEY}", "Content-Type": "application/json"},
                json=payload
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens

    async def route(self, messages: List[Dict], provider: str, model: str, max_tokens: int = 4000) -> Tuple[str, int]:
        if provider == "deepseek":
            if not CONFIG.DEEPSEEK_API_KEY:
                raise ValueError("DEEPSEEK_API_KEY is not set")
            return await self.call_deepseek(messages, model, max_tokens)
        elif provider == "kimi":
            if not CONFIG.KIMI_API_KEY:
                fallback = CONFIG.DEEPSEEK_FALLBACK_MODEL
                logger.warning(
                    "KIMI_API_KEY not set — falling back to deepseek (%s) for provider='kimi' request",
                    fallback,
                )
                return await self.call_deepseek(messages, fallback, max_tokens)
            return await self.call_kimi(messages, model, max_tokens)
        else:
            raise ValueError(f"Unknown provider: {provider}")
