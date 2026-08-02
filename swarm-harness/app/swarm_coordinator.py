# app/swarm_coordinator.py
import asyncio
import json
import hashlib
import re
from datetime import datetime
from typing import List, Dict
from app.models import SwarmBuild, BuildState, AgentConfig, AgentRole, Step
from app.llm_router import LLMRouter
from app.agent_pool import AgentPool
from app.persistence import RedisStore
from app.notifications import NotificationDispatcher
from app.state_machine import can_transition

HUMAN_INPUT_TAG = "[HUMAN_INPUT]"

class SwarmCoordinator:
    def __init__(self):
        self.store = RedisStore()
        self.notifier = NotificationDispatcher()
        self.router = LLMRouter()
        self.pool = AgentPool(self.router, self.store)

    async def submit(self, prompt: str, agents: List[AgentConfig], token_budget: int = 50000, strategy: str = "swarm") -> str:
        build_id = hashlib.sha256(f"{prompt}{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]
        build = SwarmBuild(
            id=build_id,
            prompt=prompt,
            state=BuildState.QUEUED,
            strategy=strategy,
            agents=agents,
            token_budget_total=token_budget
        )
        await self.store.save(build)
        asyncio.create_task(self._run(build))
        return build_id

    async def _transition(self, build: SwarmBuild, new_state: BuildState):
        if not can_transition(build.state, new_state):
            raise ValueError(f"Invalid transition: {build.state.value} -> {new_state.value}")
        build.state = new_state
        build.updated_at = datetime.utcnow().isoformat()
        await self.store.save(build)

    async def _run(self, build: SwarmBuild):
        async with self.router:
            try:
                # Phase 1: Planning (skipped when resuming from a human gate)
                if build.state == BuildState.QUEUED:
                    await self._transition(build, BuildState.PLANNING)

                    # Single planner agent, usually DeepSeek for reasoning
                    planner = next((a for a in build.agents if a.role == AgentRole.PLANNER), build.agents[0])
                    plan_messages = [
                        {"role": "system", "content": planner.system_prompt or "You are a technical planner. Break requests into executable sub-tasks."},
                        {"role": "user", "content": f"Plan this build: {build.prompt}\n\nOutput JSON array of sub-tasks with 'description', 'role' (coder/reviewer/tester). If a sub-task needs human clarification, prefix its description with {HUMAN_INPUT_TAG}."}
                    ]
                    plan_text, plan_tokens = await self.router.route(plan_messages, planner.provider.value, planner.model)
                    build.token_usage += plan_tokens

                    # Parse plan
                    try:
                        plan = json.loads(plan_text)
                    except json.JSONDecodeError:
                        # Fallback: extract JSON from markdown
                        json_match = re.search(r'\[.*\]', plan_text, re.DOTALL)
                        plan = json.loads(json_match.group()) if json_match else [{"description": build.prompt, "role": "coder"}]
                    build.context["plan"] = plan

                    await self._transition(build, BuildState.EXECUTING)

                    # Create execution steps from the plan
                    for i, task in enumerate(plan[:5]):  # Max 5 parallel tasks
                        agent = next((a for a in build.agents if a.role.value == task.get("role", "coder")), build.agents[0])
                        step = Step(
                            id=f"{build.id}_step_{i}",
                            agent_id=f"{agent.role.value}_{agent.provider.value}",
                            role=agent.role,
                            provider=agent.provider,
                            prompt=task["description"]
                        )
                        build.steps.append(step)
                    await self.store.save(build)

                # Human gate: pause if a step asks for input
                gate = next((s for s in build.steps if s.prompt.startswith(HUMAN_INPUT_TAG) and not s.result), None)
                if gate:
                    question = gate.prompt.replace(HUMAN_INPUT_TAG, "").strip()
                    build.human_input_queue.append({"step_id": gate.id, "question": question})
                    await self._transition(build, BuildState.WAITING_HUMAN)
                    await self.notifier.notify(build, f"🛑 Build paused. Input needed: {question}", "high")
                    return  # Resumes via human_input()

                # Phase 2: Parallel execution of pending steps
                pending = [s for s in build.steps if s.role != AgentRole.REVIEWER and not s.result and not s.error]
                step_futures = []
                for step in pending:
                    agent = next((a for a in build.agents if a.role == step.role), build.agents[0])
                    step_futures.append(self.pool.execute_step(build, step, agent))

                results = await asyncio.gather(*step_futures, return_exceptions=True)

                # Check for failures
                failures = [r for r in results if isinstance(r, Exception)]
                if pending and len(failures) > len(pending) / 2:
                    build.error_log.append(f"Majority of swarm failed: {failures}")
                    await self._transition(build, BuildState.FAILED)
                    await self.notifier.notify(build, "❌ Swarm failed: majority of agents failed", "high")
                    return

                await self._transition(build, BuildState.REVIEWING)

                # Phase 3: Cross-Review (parallel), one review per unreviewed output
                review_futures = []
                for step in build.steps:
                    if step.role == AgentRole.REVIEWER or not step.result or step.error:
                        continue
                    if any(r.id == f"{step.id}_review" for r in build.steps):
                        continue  # Already reviewed (e.g. resumed build)
                    reviewer = next((a for a in build.agents if a.role == AgentRole.REVIEWER), None)
                    if reviewer:
                        review_step = Step(
                            id=f"{step.id}_review",
                            agent_id=f"{reviewer.role.value}_{reviewer.provider.value}",
                            role=AgentRole.REVIEWER,
                            provider=reviewer.provider,
                            prompt=f"Review this output for correctness and completeness. Approve or reject with reason:\n\n{step.result}"
                        )
                        build.steps.append(review_step)
                        review_futures.append(self.pool.execute_step(build, review_step, reviewer))

                await asyncio.gather(*review_futures)

                # Check approvals
                for step in build.steps:
                    if step.role == AgentRole.REVIEWER and step.result:
                        step.approved = "approve" in step.result.lower() or "correct" in step.result.lower()

                unapproved = [s for s in build.steps if s.role != AgentRole.REVIEWER and not any(
                    r.approved for r in build.steps if r.id == f"{s.id}_review"
                )]

                if unapproved and build.token_usage < build.token_budget_total * 0.8:
                    # Retry unapproved steps once
                    retry_futures = []
                    for step in unapproved:
                        step.retry_count += 1
                        agent = next((a for a in build.agents if a.role == step.role), build.agents[0])
                        retry_futures.append(self.pool.execute_step(build, step, agent))
                    await asyncio.gather(*retry_futures)

                # Phase 4: Merge
                await self._transition(build, BuildState.MERGING)
                merger = next((a for a in build.agents if a.role == AgentRole.MERGER), build.agents[0])
                merge_context = "\n\n".join([
                    f"--- {s.role.value} ---\n{s.result}"
                    for s in build.steps
                    if s.result and s.role != AgentRole.REVIEWER
                ])
                merge_messages = [
                    {"role": "system", "content": merger.system_prompt or "You are a tech lead. Combine outputs into a final deliverable."},
                    {"role": "user", "content": f"Original request: {build.prompt}\n\nAgent outputs:\n{merge_context}"}
                ]
                final_output, merge_tokens = await self.router.route(merge_messages, merger.provider.value, merger.model)
                build.token_usage += merge_tokens
                build.final_output = final_output

                await self._transition(build, BuildState.COMPLETED)
                await self.notifier.notify(build, f"✅ Swarm complete! Tokens: {build.token_usage}", "normal")

            except Exception as e:
                build.error_log.append(str(e))
                if build.state not in (BuildState.FAILED, BuildState.CANCELLED):
                    await self._transition(build, BuildState.FAILED)
                await self.notifier.notify(build, f"❌ Swarm failed: {e}", "high")

    async def human_input(self, build_id: str, response: str) -> Dict:
        build = await self.store.load(build_id)
        if not build or build.state != BuildState.WAITING_HUMAN:
            return {"error": "Build not found or not waiting for input"}

        build.context["human_input"] = response
        # Fold the answer into the paused step(s) so re-execution uses it
        # and the gate does not trigger again.
        for s in build.steps:
            if s.prompt.startswith(HUMAN_INPUT_TAG) and not s.result:
                s.prompt = s.prompt.replace(HUMAN_INPUT_TAG, f"[HUMAN_INPUT: {response}]")

        await self._transition(build, BuildState.EXECUTING)
        asyncio.create_task(self._run(build))  # Resume from checkpoint
        return {"status": "resumed", "build_id": build_id}
