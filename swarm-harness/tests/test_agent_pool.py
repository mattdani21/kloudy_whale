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


class _RecordingRouter:
    def __init__(self, result="ok"):
        self.result = result
        self.received = []

    async def route(self, messages, provider, model, max_tokens=4000):
        self.received.append(messages)
        return (self.result, 5)


@pytest.mark.asyncio
async def test_execute_step_omits_empty_system_message():
    """Moonshot rejects an empty 'system' message (DeepSeek tolerates it) — skip it."""
    router = _RecordingRouter()
    pool = AgentPool(router, _FakeStore())
    build = SwarmBuild(id="b1", prompt="p", state=BuildState.EXECUTING, token_budget_total=1000)
    step = Step(id="s1", agent_id="a", role=AgentRole.CODER, provider=ModelProvider.KIMI, prompt="write code")
    agent = AgentConfig(role=AgentRole.CODER, provider=ModelProvider.KIMI, model="kimi-k3")  # no system_prompt

    await pool.execute_step(build, step, agent)
    assert router.received[0] == [{"role": "user", "content": "write code"}]
    assert step.result == "ok"


@pytest.mark.asyncio
async def test_execute_step_keeps_nonempty_system_message():
    router = _RecordingRouter()
    pool = AgentPool(router, _FakeStore())
    build = SwarmBuild(id="b1", prompt="p", state=BuildState.EXECUTING, token_budget_total=1000)
    step = Step(id="s1", agent_id="a", role=AgentRole.CODER, provider=ModelProvider.KIMI, prompt="write code")
    agent = AgentConfig(role=AgentRole.CODER, provider=ModelProvider.KIMI, model="kimi-k3",
                        system_prompt="You are a careful coder.")

    await pool.execute_step(build, step, agent)
    assert router.received[0] == [
        {"role": "system", "content": "You are a careful coder."},
        {"role": "user", "content": "write code"},
    ]


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
