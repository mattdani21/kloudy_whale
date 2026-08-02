# app/persistence.py
import json
from typing import List, Optional
import redis.asyncio as redis
from app.models import SwarmBuild, BuildState, AgentConfig, AgentRole, ModelProvider, Step
from app.config import CONFIG

class RedisStore:
    def __init__(self):
        self.client = redis.from_url(CONFIG.REDIS_URL, decode_responses=True)

    async def save(self, build: SwarmBuild):
        data = {
            "id": build.id,
            "prompt": build.prompt,
            "state": build.state.value,
            "strategy": build.strategy,
            "agents": [self._agent_to_dict(a) for a in build.agents],
            "steps": [self._step_to_dict(s) for s in build.steps],
            "context": build.context,
            "token_usage": build.token_usage,
            "token_budget_total": build.token_budget_total,
            "human_input_queue": build.human_input_queue,
            "created_at": build.created_at,
            "updated_at": build.updated_at,
            "final_output": build.final_output,
            "error_log": build.error_log,
            "metadata": build.metadata
        }
        await self.client.setex(f"swarm:build:{build.id}", 604800, json.dumps(data))  # 7 days

    async def load(self, build_id: str) -> Optional[SwarmBuild]:
        data = await self.client.get(f"swarm:build:{build_id}")
        if not data:
            return None
        return self._dict_to_build(json.loads(data))

    async def list(self, limit: int = 50, offset: int = 0) -> List[SwarmBuild]:
        keys = [k async for k in self.client.scan_iter("swarm:build:*")]
        keys = sorted(keys)[offset:offset + limit]
        builds = []
        for key in keys:
            data = await self.client.get(key)
            if data:
                builds.append(self._dict_to_build(json.loads(data)))
        return builds

    def _dict_to_build(self, d) -> SwarmBuild:
        return SwarmBuild(
            id=d["id"],
            prompt=d["prompt"],
            state=BuildState(d["state"]),
            strategy=d.get("strategy", "swarm"),
            agents=[self._dict_to_agent(a) for a in d.get("agents", [])],
            steps=[self._dict_to_step(s) for s in d.get("steps", [])],
            context=d.get("context", {}),
            token_usage=d.get("token_usage", 0),
            token_budget_total=d.get("token_budget_total", 50000),
            human_input_queue=d.get("human_input_queue", []),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            final_output=d.get("final_output"),
            error_log=d.get("error_log", []),
            metadata=d.get("metadata", {})
        )

    def _agent_to_dict(self, a):
        return {"role": a.role.value, "provider": a.provider.value, "model": a.model, "temperature": a.temperature, "max_tokens": a.max_tokens, "system_prompt": a.system_prompt, "token_budget": a.token_budget}

    def _dict_to_agent(self, d):
        return AgentConfig(role=AgentRole(d["role"]), provider=ModelProvider(d["provider"]), model=d["model"], temperature=d.get("temperature", 0.7), max_tokens=d.get("max_tokens", 4000), system_prompt=d.get("system_prompt", ""), token_budget=d.get("token_budget", 20000))

    def _step_to_dict(self, s):
        return {"id": s.id, "agent_id": s.agent_id, "role": s.role.value, "provider": s.provider.value, "prompt": s.prompt, "result": s.result, "review": s.review, "approved": s.approved, "tokens_used": s.tokens_used, "duration_ms": s.duration_ms, "retry_count": s.retry_count, "error": s.error, "created_at": s.created_at, "completed_at": s.completed_at}

    def _dict_to_step(self, d):
        return Step(id=d["id"], agent_id=d["agent_id"], role=AgentRole(d["role"]), provider=ModelProvider(d["provider"]), prompt=d["prompt"], result=d.get("result"), review=d.get("review"), approved=d.get("approved", False), tokens_used=d.get("tokens_used", 0), duration_ms=d.get("duration_ms", 0.0), retry_count=d.get("retry_count", 0), error=d.get("error"), created_at=d["created_at"], completed_at=d.get("completed_at"))
