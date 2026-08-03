# app/swarm_coordinator.py
import asyncio
import json
import hashlib
import re
from datetime import datetime
from typing import List, Dict, Optional
from app.models import SwarmBuild, BuildState, AgentConfig, AgentRole, Step, RepoConfig
from app.llm_router import LLMRouter
from app.agent_pool import AgentPool
from app.persistence import RedisStore
from app.notifications import NotificationDispatcher
from app.state_machine import can_transition
from app.github_client import GitHubRepoClient
from app.agent_pool import unwrap_error

HUMAN_INPUT_TAG = "[HUMAN_INPUT]"

REPO_MANIFEST_INSTRUCTION = (
    "Output ONLY a JSON array of file objects: "
    '[{"path": "<repo-relative path>", "content": "<complete file content>"}, ...]. '
    "Every file the sub-task needs must be its own object with full content. No prose, no markdown fences."
)

def _parse_file_manifest(text: str):
    """Parse a coder's output into {path: content}. Tolerant of markdown fences."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return None
    if not isinstance(data, list):
        return None
    files = {}
    for item in data:
        if isinstance(item, dict) and item.get("path") and item.get("content") is not None:
            files[str(item["path"]).lstrip("/")] = str(item["content"])
    return files or None

class SwarmCoordinator:
    def __init__(self):
        self.store = RedisStore()
        self.notifier = NotificationDispatcher()
        self.router = LLMRouter()
        self.pool = AgentPool(self.router, self.store)

    async def submit(self, prompt: str, agents: List[AgentConfig], token_budget: int = 4000000, strategy: str = "swarm", repo: Optional[RepoConfig] = None) -> str:
        build_id = hashlib.sha256(f"{prompt}{datetime.utcnow().isoformat()}".encode()).hexdigest()[:12]
        build = SwarmBuild(
            id=build_id,
            prompt=prompt,
            state=BuildState.QUEUED,
            strategy=strategy,
            agents=agents,
            token_budget_total=token_budget
        )
        if repo:
            build.metadata["repo"] = {"owner": repo.owner, "name": repo.name, "token": repo.token, "branch": repo.branch}
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
                    plan_text, plan_tokens = await self.router.route(plan_messages, planner.provider.value, planner.model, planner.max_tokens)
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
                    repo_mode = bool(build.metadata.get("repo"))
                    for i, task in enumerate(plan[:5]):  # Max 5 parallel tasks
                        agent = next((a for a in build.agents if a.role.value == task.get("role", "coder")), build.agents[0])
                        task_prompt = task["description"]
                        if repo_mode and agent.role in (AgentRole.CODER, AgentRole.TESTER):
                            task_prompt += "\n\n" + REPO_MANIFEST_INSTRUCTION
                        step = Step(
                            id=f"{build.id}_step_{i}",
                            agent_id=f"{agent.role.value}_{agent.provider.value}",
                            role=agent.role,
                            provider=agent.provider,
                            prompt=task_prompt
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
                failures = [unwrap_error(r) for r in results if isinstance(r, Exception)]
                if pending and len(failures) > len(pending) / 2:
                    build.error_log.append(f"Majority of swarm failed: {failures}")
                    await self._transition(build, BuildState.FAILED)
                    await self.notifier.notify(build, "❌ Swarm failed: majority of agents failed", "high")
                    return

                # Repo mode: collect file manifests produced by coder steps
                if build.metadata.get("repo"):
                    manifest = {}
                    for s in build.steps:
                        if s.result and s.role in (AgentRole.CODER, AgentRole.TESTER):
                            parsed = _parse_file_manifest(s.result)
                            if parsed:
                                manifest.update(parsed)
                    build.context["manifest"] = manifest
                    build.context["staged_files"] = list(manifest.keys())
                    await self.store.save(build)

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

                # Phase 3.5: Repo write + verify (repo mode only)
                repo_meta = build.metadata.get("repo")
                if repo_meta:
                    await self._repo_write_and_verify(build, repo_meta)

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
                final_output, merge_tokens = await self.router.route(merge_messages, merger.provider.value, merger.model, merger.max_tokens)
                build.token_usage += merge_tokens
                build.final_output = final_output
                if repo_meta and build.metadata.get("commit_sha"):
                    files = build.metadata.get("files_written", [])
                    build.final_output += (
                        f"\n\n---\n✅ **Written to GitHub:** {repo_meta['owner']}/{repo_meta['name']}"
                        f" ({repo_meta.get('branch') or 'default branch'}) · commit `{build.metadata['commit_sha'][:10]}`\n"
                        f"Files: {', '.join(files) if files else '(none — see notes)'}\n"
                        f"Verification: {build.context.get('verification', 'n/a')}"
                    )

                await self._transition(build, BuildState.COMPLETED)
                await self.notifier.notify(build, f"✅ Swarm complete! Tokens: {build.token_usage}", "normal")

            except Exception as e:
                e = unwrap_error(e)
                build.error_log.append(str(e))
                if build.state not in (BuildState.FAILED, BuildState.CANCELLED):
                    await self._transition(build, BuildState.FAILED)
                await self.notifier.notify(build, f"❌ Swarm failed: {e}", "high")

    async def _repo_write_and_verify(self, build: SwarmBuild, repo_meta: Dict):
        """Write staged file manifests to the GitHub repo, then verify done-or-needs-work.

        Verifier agent reads the repo back and compares against the request; if work
        is missing and token budget remains, one extra coder round fixes the gaps.
        """
        # Collect manifests from all coder/tester steps (post-retry state)
        manifest = {}
        for s in build.steps:
            if s.result and s.role in (AgentRole.CODER, AgentRole.TESTER):
                parsed = _parse_file_manifest(s.result)
                if parsed:
                    manifest.update(parsed)
        build.context["manifest"] = manifest
        await self.store.save(build)

        try:
            async with GitHubRepoClient(repo_meta["owner"], repo_meta["name"], repo_meta["token"], repo_meta.get("branch")) as client:
                if manifest:
                    commit_info = await client.write_files(
                        manifest,
                        f"DeepKimi build {build.id}: {build.prompt[:80]}",
                    )
                    build.metadata["files_written"] = commit_info["files"]
                    build.metadata["commit_sha"] = commit_info["commit"]
                    await self.store.save(build)

                # Verify: read the repo back; is the work done or does it need more?
                verifier = next((a for a in build.agents if a.role == AgentRole.REVIEWER), build.agents[0])
                files = await client.list_files()
                file_list = "\n".join(files[:300])
                verify_messages = [
                    {"role": "system", "content": verifier.system_prompt or "You verify that completed work matches the request."},
                    {"role": "user", "content": (
                        f"Original request: {build.prompt}\n\n"
                        f"Files currently in the repo:\n{file_list}\n\n"
                        "Compare the request against the files present. If the work is complete, "
                        "reply with exactly 'DONE'. If anything is missing or broken, reply with a "
                        "short list of what still needs work."
                    )},
                ]
                verify_text, verify_tokens = await self.router.route(verify_messages, verifier.provider.value, verifier.model, verifier.max_tokens)
                build.token_usage += verify_tokens
                done = verify_text.strip().upper().startswith("DONE")
                build.context["verifier_report"] = verify_text
                build.context["verification"] = "done" if done else "needs_work"
                await self.store.save(build)

                if not done and build.token_usage < build.token_budget_total * 0.8:
                    coder = next((a for a in build.agents if a.role == AgentRole.CODER), build.agents[0])
                    gap_step = Step(
                        id=f"{build.id}_gapfix",
                        agent_id=f"coder_{coder.provider.value}",
                        role=AgentRole.CODER,
                        provider=coder.provider,
                        prompt=f"Complete the missing work:\n{verify_text}\n\n{REPO_MANIFEST_INSTRUCTION}",
                    )
                    build.steps.append(gap_step)
                    await self.store.save(build)
                    await self.pool.execute_step(build, gap_step, coder)
                    gap_manifest = _parse_file_manifest(gap_step.result) if gap_step.result else None
                    if gap_manifest:
                        commit_info = await client.write_files(
                            gap_manifest,
                            f"DeepKimi build {build.id}: follow-up ({verify_text[:60]})",
                        )
                        build.metadata["files_written"] = sorted(set(build.metadata.get("files_written", [])) | set(commit_info["files"]))
                        build.metadata["commit_sha"] = commit_info["commit"]
                        await self.store.save(build)
        except Exception as e:
            build.error_log.append(f"Repo write failed: {e}")
            await self.notifier.notify(build, f"⚠️ Repo write failed: {e}", "high")

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
