# app/agent_pool.py
from datetime import datetime
from tenacity import RetryError
from app.models import SwarmBuild, Step, AgentConfig
from app.llm_router import LLMRouter
from app.persistence import RedisStore

def unwrap_error(e: Exception) -> Exception:
    """Unwrap tenacity's RetryError so the underlying provider error surfaces."""
    if isinstance(e, RetryError) and e.last_attempt:
        exc = e.last_attempt.exception()
        if isinstance(exc, Exception):
            return exc
        if exc is not None:  # BaseException (e.g. KeyboardInterrupt) — wrap it
            return RuntimeError(str(exc))
    return e

class AgentPool:
    """Executes individual steps against the LLM router with budget enforcement."""

    def __init__(self, router: LLMRouter, store: RedisStore):
        self.router = router
        self.store = store

    async def execute_step(self, build: SwarmBuild, step: Step, agent: AgentConfig):
        if build.token_usage >= build.token_budget_total:
            raise Exception("Token budget exhausted")

        messages = []
        if agent.system_prompt:
            messages.append({"role": "system", "content": agent.system_prompt})
        messages.append({"role": "user", "content": step.prompt})
        start = datetime.utcnow()
        try:
            result, tokens = await self.router.route(messages, agent.provider.value, agent.model, agent.max_tokens)
            step.result = result
            step.tokens_used = tokens
            build.token_usage += tokens
            step.completed_at = datetime.utcnow().isoformat()
            step.duration_ms = (datetime.utcnow() - start).total_seconds() * 1000
            await self.store.save(build)
        except Exception as e:
            e = unwrap_error(e)
            step.error = str(e)
            step.completed_at = datetime.utcnow().isoformat()
            await self.store.save(build)
            raise
