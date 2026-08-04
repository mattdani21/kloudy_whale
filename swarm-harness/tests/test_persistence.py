import pytest
from app.models import AgentConfig, AgentRole, BuildState, ModelProvider, Step, SwarmBuild
from app.persistence import RedisStore

class FakeRedis:
    """In-memory stand-in for redis.asyncio client."""
    def __init__(self):
        self.data = {}

    async def setex(self, key, ttl, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        for key in list(self.data):
            if key.startswith(prefix):
                yield key

def make_build(build_id="b1", state=BuildState.QUEUED):
    return SwarmBuild(
        id=build_id,
        prompt="build a thing",
        state=state,
        agents=[
            AgentConfig(role=AgentRole.PLANNER, provider=ModelProvider.DEEPSEEK, model="deepseek-v4-flash"),
            AgentConfig(role=AgentRole.CODER, provider=ModelProvider.KIMI, model="kimi-k3", token_budget=30000),
        ],
        steps=[
            Step(id="b1_step_0", agent_id="coder_kimi", role=AgentRole.CODER,
                 provider=ModelProvider.KIMI, prompt="write code", result="print('hi')",
                 approved=True, tokens_used=123, duration_ms=45.6)
        ],
        context={"plan": "[]"},
        token_usage=123,
        token_budget_total=40000,
        human_input_queue=[{"question": "which db?"}],
        final_output="done",
        error_log=["oops"],
        metadata={"slack_webhook": "https://hooks.slack.com/x"},
    )

@pytest.fixture
def store():
    s = RedisStore()
    s.client = FakeRedis()
    return s

@pytest.mark.asyncio
async def test_save_load_round_trip(store):
    original = make_build()
    await store.save(original)
    loaded = await store.load("b1")

    assert loaded is not None
    assert loaded.id == "b1"
    assert loaded.prompt == original.prompt
    assert loaded.state == BuildState.QUEUED
    assert loaded.strategy == "swarm"
    assert loaded.token_usage == 123
    assert loaded.token_budget_total == 40000
    assert loaded.context == {"plan": "[]"}
    assert loaded.human_input_queue == [{"question": "which db?"}]
    assert loaded.final_output == "done"
    assert loaded.error_log == ["oops"]
    assert loaded.metadata == {"slack_webhook": "https://hooks.slack.com/x"}

    planner, coder = loaded.agents
    assert planner.role == AgentRole.PLANNER
    assert planner.provider == ModelProvider.DEEPSEEK
    assert coder.token_budget == 30000

    step = loaded.steps[0]
    assert step.role == AgentRole.CODER
    assert step.provider == ModelProvider.KIMI
    assert step.result == "print('hi')"
    assert step.approved is True
    assert step.tokens_used == 123
    assert step.duration_ms == 45.6

@pytest.mark.asyncio
async def test_load_missing_returns_none(store):
    assert await store.load("nope") is None

@pytest.mark.asyncio
async def test_list_with_pagination(store):
    for i in range(5):
        await store.save(make_build(build_id=f"b{i}"))

    all_builds = await store.list()
    assert len(all_builds) == 5

    page = await store.list(limit=2, offset=1)
    assert len(page) == 2

    empty = await store.list(limit=2, offset=10)
    assert empty == []
