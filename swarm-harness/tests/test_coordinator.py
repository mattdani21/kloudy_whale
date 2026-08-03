import asyncio
import pytest

from app.models import AgentConfig, AgentRole, BuildState, ModelProvider, SwarmBuild
from app.swarm_coordinator import SwarmCoordinator, _gate_question, HUMAN_INPUT_TAG, REPO_MANIFEST_INSTRUCTION

class FakeRouter:
    """Canned LLM responses keyed off the prompt content."""
    def __init__(self, plan='[{"description": "write the code", "role": "coder"}, {"description": "write tests", "role": "tester"}]', fail_steps=False):
        self.plan = plan
        self.fail_steps = fail_steps
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def route(self, messages, provider, model, max_tokens=4000):
        user = messages[-1]["content"]
        self.calls.append((provider, model, user[:40]))
        if "Plan this build" in user:
            return (self.plan, 10)
        if "Review this output" in user:
            return ("approved: looks correct", 5)
        if "Agent outputs" in user:
            return ("FINAL DELIVERABLE", 20)
        if self.fail_steps:
            raise Exception("LLM API down")
        return (f"output for: {user[:30]}", 15)

class FakeStore:
    def __init__(self):
        self.builds = {}

    async def save(self, build):
        self.builds[build.id] = build

    async def load(self, build_id):
        return self.builds.get(build_id)

    async def list(self, limit=50, offset=0):
        return list(self.builds.values())[offset:offset + limit]

class FakeNotifier:
    def __init__(self):
        self.events = []

    async def notify(self, build, message, urgency="normal"):
        self.events.append({"build_id": build.id, "state": build.state.value,
                            "message": message, "urgency": urgency})

AGENTS = [
    AgentConfig(role=AgentRole.PLANNER, provider=ModelProvider.DEEPSEEK, model="deepseek-chat"),
    AgentConfig(role=AgentRole.CODER, provider=ModelProvider.KIMI, model="kimi-k3"),
    AgentConfig(role=AgentRole.TESTER, provider=ModelProvider.DEEPSEEK, model="deepseek-chat"),
    AgentConfig(role=AgentRole.REVIEWER, provider=ModelProvider.DEEPSEEK, model="deepseek-chat"),
    AgentConfig(role=AgentRole.MERGER, provider=ModelProvider.KIMI, model="kimi-k3"),
]

def make_coordinator(router) -> SwarmCoordinator:
    c = SwarmCoordinator()
    c.store = FakeStore()
    c.pool.store = c.store
    c.router = router
    c.pool.router = router
    c.notifier = FakeNotifier()
    return c

def make_build(build_id="b1"):
    return SwarmBuild(id=build_id, prompt="build a cli tool", state=BuildState.QUEUED,
                      agents=AGENTS, token_budget_total=40000)

@pytest.mark.asyncio
async def test_full_pipeline_completes():
    router = FakeRouter()
    c = make_coordinator(router)
    build = make_build()

    await c._run(build)

    assert build.state == BuildState.COMPLETED
    assert build.final_output == "FINAL DELIVERABLE"
    # plan(10) + 2 steps(15 each) + 2 reviews(5 each) + merge(20)
    assert build.token_usage == 70

    exec_steps = [s for s in build.steps if s.role != AgentRole.REVIEWER]
    review_steps = [s for s in build.steps if s.role == AgentRole.REVIEWER]
    assert len(exec_steps) == 2
    assert len(review_steps) == 2
    assert all(s.approved for s in review_steps)
    assert all(s.completed_at for s in build.steps)
    assert build.error_log == []
    # Completion notification fired
    assert any("complete" in e["message"] for e in c.notifier.events)

@pytest.mark.asyncio
async def test_submit_persists_and_runs():
    router = FakeRouter()
    c = make_coordinator(router)

    build_id = await c.submit("build a cli tool", AGENTS, token_budget=40000)

    assert len(build_id) == 12
    await asyncio.sleep(0.3)  # let the background task finish
    build = await c.store.load(build_id)
    assert build is not None
    assert build.state == BuildState.COMPLETED
    assert build.final_output == "FINAL DELIVERABLE"

@pytest.mark.asyncio
async def test_human_gate_pauses_and_resumes():
    router = FakeRouter(plan='[{"description": "[HUMAN_INPUT] which database should I use?", "role": "coder"}, {"description": "write tests", "role": "tester"}]')
    c = make_coordinator(router)
    build = make_build()

    await c._run(build)

    assert build.state == BuildState.WAITING_HUMAN
    assert build.human_input_queue[-1]["question"] == "which database should I use?"
    assert any(e["urgency"] == "high" for e in c.notifier.events)
    # Nothing executed yet — the gate pauses before spending step tokens
    assert all(not s.result for s in build.steps)

    result = await c.human_input(build.id, "use postgres")
    assert result["status"] == "resumed"
    await asyncio.sleep(0.3)  # let the resumed task finish

    resumed = await c.store.load(build.id)
    assert resumed.state == BuildState.COMPLETED
    assert resumed.context["human_input"] == "use postgres"
    assert "use postgres" in resumed.steps[0].prompt
    assert resumed.final_output == "FINAL DELIVERABLE"

@pytest.mark.asyncio
async def test_human_input_rejected_when_not_waiting():
    c = make_coordinator(FakeRouter())
    build = make_build()
    await c.store.save(build)
    assert "error" in await c.human_input(build.id, "hello")
    assert "error" in await c.human_input("missing", "hello")

@pytest.mark.asyncio
async def test_majority_failure_marks_failed():
    router = FakeRouter(fail_steps=True)
    c = make_coordinator(router)
    build = make_build()

    await c._run(build)

    assert build.state == BuildState.FAILED
    assert any("Majority" in e for e in build.error_log)
    assert any(e["urgency"] == "high" for e in c.notifier.events)

@pytest.mark.asyncio
async def test_plan_fallback_when_not_json():
    router = FakeRouter(plan="Sorry, I cannot produce JSON for this.")
    c = make_coordinator(router)
    build = make_build()

    await c._run(build)

    # Falls back to a single coder step using the raw prompt
    assert build.state == BuildState.COMPLETED
    exec_steps = [s for s in build.steps if s.role != AgentRole.REVIEWER]
    assert len(exec_steps) == 1
    assert exec_steps[0].prompt == build.prompt

@pytest.mark.asyncio
async def test_invalid_transition_raises():
    c = make_coordinator(FakeRouter())
    build = make_build()
    build.state = BuildState.COMPLETED
    with pytest.raises(ValueError):
        await c._transition(build, BuildState.PLANNING)


def test_gate_question_strips_tag_and_manifest_boilerplate():
    prompt = f"{HUMAN_INPUT_TAG} Confirm the target stack: React or Vue?\n\n{REPO_MANIFEST_INSTRUCTION}"
    assert _gate_question(prompt) == "Confirm the target stack: React or Vue?"


def test_gate_question_plain_prompt_unchanged():
    assert _gate_question(f"{HUMAN_INPUT_TAG} Which database?") == "Which database?"
