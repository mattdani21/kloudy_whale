# tests/test_llm_router.py
import pytest
from types import SimpleNamespace

from app import llm_router
from app.llm_router import LLMRouter

FALLBACK_MODEL = "deepseek-v4-flash-ultra-reasoning"


def make_config(kimi_key: str):
    return SimpleNamespace(
        KIMI_API_KEY=kimi_key,
        KIMI_API_BASE="https://api.moonshot.ai/v1",
        DEEPSEEK_API_KEY="sk-test",
        DEEPSEEK_FALLBACK_MODEL=FALLBACK_MODEL,
    )


@pytest.mark.asyncio
async def test_kimi_without_key_falls_back_to_deepseek(monkeypatch):
    """A 'kimi' agent must route to DeepSeek (fallback model) when KIMI_API_KEY is missing."""
    router = LLMRouter()
    monkeypatch.setattr(llm_router, "CONFIG", make_config(kimi_key=""))
    calls = {}

    async def fake_deepseek(messages, model, max_tokens=4000):
        calls["model"] = model
        return ("deepseek-result", 10)

    async def fail_kimi(messages, model, max_tokens=4000):
        raise AssertionError("call_kimi must not be called without a key")

    monkeypatch.setattr(router, "call_deepseek", fake_deepseek)
    monkeypatch.setattr(router, "call_kimi", fail_kimi)

    result, tokens = await router.route([{"role": "user", "content": "hi"}], "kimi", "kimi-k3")
    assert result == "deepseek-result"
    assert tokens == 10
    assert calls["model"] == FALLBACK_MODEL


@pytest.mark.asyncio
async def test_kimi_with_key_uses_kimi(monkeypatch):
    """A 'kimi' agent must use Kimi when KIMI_API_KEY is set (no fallback)."""
    router = LLMRouter()
    monkeypatch.setattr(llm_router, "CONFIG", make_config(kimi_key="sk-real"))

    async def fake_kimi(messages, model, max_tokens=4000):
        return ("kimi-result", 5)

    async def fail_deepseek(messages, model, max_tokens=4000):
        raise AssertionError("call_deepseek must not be called when kimi key exists")

    monkeypatch.setattr(router, "call_kimi", fake_kimi)
    monkeypatch.setattr(router, "call_deepseek", fail_deepseek)

    result, tokens = await router.route([{"role": "user", "content": "hi"}], "kimi", "kimi-k3")
    assert result == "kimi-result"
    assert tokens == 5


@pytest.mark.asyncio
async def test_deepseek_without_key_raises(monkeypatch):
    """A 'deepseek' agent without DEEPSEEK_API_KEY must raise a clear error."""
    router = LLMRouter()
    monkeypatch.setattr(
        llm_router, "CONFIG", SimpleNamespace(KIMI_API_KEY="", KIMI_API_BASE="https://api.moonshot.ai/v1", DEEPSEEK_API_KEY="", DEEPSEEK_FALLBACK_MODEL=FALLBACK_MODEL)
    )

    async def fail_deepseek(messages, model, max_tokens=4000):
        raise AssertionError("call_deepseek must not be called without a key")

    monkeypatch.setattr(router, "call_deepseek", fail_deepseek)

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        await router.route([], "deepseek", "deepseek-chat")


@pytest.mark.asyncio
async def test_unknown_provider_raises(monkeypatch):
    router = LLMRouter()
    monkeypatch.setattr(llm_router, "CONFIG", make_config(kimi_key=""))
    with pytest.raises(ValueError, match="Unknown provider"):
        await router.route([], "gpt", "gpt-4")
