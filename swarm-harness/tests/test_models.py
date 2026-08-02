from app.models import AgentConfig, AgentRole, BuildState, ModelProvider, Step, SwarmBuild

def test_enum_values():
    assert BuildState.QUEUED.value == "queued"
    assert BuildState.WAITING_HUMAN.value == "waiting_human"
    assert AgentRole.PLANNER.value == "planner"
    assert AgentRole.MERGER.value == "merger"
    assert ModelProvider.DEEPSEEK.value == "deepseek"
    assert ModelProvider.KIMI.value == "kimi"

def test_agent_config_defaults():
    agent = AgentConfig(role=AgentRole.CODER, provider=ModelProvider.KIMI, model="kimi-k3")
    assert agent.temperature == 0.7
    assert agent.max_tokens == 16384
    assert agent.system_prompt == ""
    assert agent.token_budget == 20000

def test_step_defaults():
    step = Step(id="s1", agent_id="coder_kimi", role=AgentRole.CODER,
                provider=ModelProvider.KIMI, prompt="do it")
    assert step.result is None
    assert step.approved is False
    assert step.tokens_used == 0
    assert step.retry_count == 0
    assert step.error is None
    assert step.created_at  # auto-populated
    assert step.completed_at is None

def test_swarm_build_defaults():
    build = SwarmBuild(id="b1", prompt="build something", state=BuildState.QUEUED)
    assert build.strategy == "swarm"
    assert build.token_usage == 0
    assert build.token_budget_total == 4000000
    assert build.agents == []
    assert build.steps == []
    assert build.context == {}
    assert build.human_input_queue == []
    assert build.error_log == []
    assert build.metadata == {}
    assert build.final_output is None
    assert build.created_at and build.updated_at
