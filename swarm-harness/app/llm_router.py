# app/llm_router.py
import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import CONFIG

logger = logging.getLogger(__name__)

class LLMRouter:
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        # Per-provider concurrency semaphores: parallel steps must actually run in
        # parallel (a global lock serialized every LLM call — the swarm's biggest
        # latency bug), but a small cap avoids tripping provider rate limits.
        self._sems: Dict[str, asyncio.Semaphore] = {}

    def _sem(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._sems:
            limit = CONFIG.LLM_CONCURRENCY
            self._sems[provider] = asyncio.Semaphore(limit) if limit > 0 else asyncio.Semaphore(10**6)
        return self._sems[provider]

    async def __aenter__(self):
        # 600s total: long reasoning merges on big builds exceed 120s
        timeout = aiohttp.ClientTimeout(total=600, connect=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_deepseek(self, messages: List[Dict], model: Optional[str] = None, max_tokens: int = 4000) -> Tuple[str, int]:
        model = model or CONFIG.DEEPSEEK_MODEL
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": False
        }
        return await self._post_and_parse(
            "https://api.deepseek.com/v1/chat/completions",
            CONFIG.DEEPSEEK_API_KEY,
            payload,
            "deepseek",
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def call_kimi(self, messages: List[Dict], model: Optional[str] = None, max_tokens: int = 4000) -> Tuple[str, int]:
        model = model or CONFIG.KIMI_MODEL
        payload = {
            "model": model,
            "messages": messages,
            # Moonshot's kimi-k3 family only accepts temperature == 1 (rejects 0.7 with 400).
            "temperature": 1,
            "max_tokens": max_tokens,
            "stream": False
        }
        return await self._post_and_parse(
            f"{CONFIG.KIMI_API_BASE.rstrip('/')}/chat/completions",
            CONFIG.KIMI_API_KEY,
            payload,
            "kimi",
        )

    async def _post_and_parse(self, url: str, api_key: str, payload: dict, provider: str) -> Tuple[str, int]:
        """POST to an OpenAI-compatible endpoint; surface HTTP errors with status + body."""
        async with self._sem(provider):
            async with self.session.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload
            ) as resp:
                if resp.status >= 400:
                    body = (await resp.text())[:300]
                    raise RuntimeError(f"{provider} API error {resp.status}: {body}")
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
