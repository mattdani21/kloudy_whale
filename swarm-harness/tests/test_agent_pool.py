# tests/test_agent_pool.py
import pytest
from tenacity import RetryError, retry, stop_after_attempt, wait_none

from app.agent_pool import AgentPool, unwrap_error
from app.models import AgentConfig, AgentRole, BuildState, ModelProvider, Step, SwarmBuild


def test_unwrap_error_surfaces_underlying_message():
    """A REAL tenacity RetryError (as produced by @retry) must unwrap to the provider message."""
    @retry(stop=stop_after_attempt(2), wait=wait_none())
    def boom():
        raise RuntimeError("kimi API error 429: rate limited")

    with pytest.raises(RetryError) as exc:
        boom()
    assert str(unwrap_error(exc.value)) == "kimi API error 429: rate limited"


def test_unwrap_error_passthrough():
    e = ValueError("plain failure")
    assert unwrap_error(e) is e


class _FakeStore:
    async def save(self, build):
        pass


class _FakeRouter:
    def __init__(self, exc: Exception):
        self.exc = exc

    async def route(self, messages, provider, model, max_tokens=4000):
        raise self.exc


@pytest.mark.asyncio
async def test_execute_step_records_underlying_error():
    """step.error must carry the underlying provider message, not an opaque wrapper."""
    pool = AgentPool(_FakeRouter(RuntimeError("kimi API error 400: model not found")), _FakeStore())
    build = SwarmBuild(id="b1", prompt="p", state=BuildState.EXECUTING, token_budget_total=1000)
    step = Step(id="s1", agent_id="a", role=AgentRole.CODER, provider=ModelProvider.KIMI, prompt="x")
    agent = AgentConfig(role=AgentRole.CODER, provider=ModelProvider.KIMI, model="kimi-k3")

    with pytest.raises(RuntimeError, match="model not found"):
        await pool.execute_step(build, step, agent)
    assert step.error == "kimi API error 400: model not found"
