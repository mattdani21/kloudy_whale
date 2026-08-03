# app/api/builds.py
import re
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import List, Optional, Literal
from app.models import AgentConfig, BuildState, RepoConfig, CreateRepoConfig
from app.swarm_coordinator import SwarmCoordinator
from app.persistence import RedisStore
from app.github_client import GitHubRepoClient, GitHubError
from app.config import CONFIG

router = APIRouter()

coordinator = SwarmCoordinator()
store = RedisStore()

REPO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key not in CONFIG.API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

class BuildRequest(BaseModel):
    prompt: str
    agents: List[AgentConfig]
    strategy: Literal["single", "swarm", "debate"] = "swarm"
    token_budget: int = 4000000
    slack_webhook: Optional[str] = None
    repo: Optional[RepoConfig] = None  # GitHub repo the build writes to
    create_repo: Optional[CreateRepoConfig] = None  # OR: create a brand-new repo first

class RespondRequest(BaseModel):
    response: str

def _build_summary(build) -> dict:
    meta = dict(build.metadata)
    repo = meta.pop("repo", None)
    if repo:
        repo = {k: v for k, v in repo.items() if k != "token"}  # never expose the PAT
    return {
        "id": build.id,
        "state": build.state.value,
        "token_usage": build.token_usage,
        "budget_total": build.token_budget_total,
        "needs_human": build.state == BuildState.WAITING_HUMAN,
        "human_question": build.human_input_queue[-1] if build.human_input_queue else None,
        "final_output": build.final_output,
        "repo": repo,
        "files_written": meta.pop("files_written", []),
        "commit_sha": meta.pop("commit_sha", None),
        "steps": [{"id": s.id, "role": s.role.value, "provider": s.provider.value, "status": "done" if s.completed_at else "pending", "tokens": s.tokens_used, "error": s.error} for s in build.steps],
        "errors": build.error_log,
    }

@router.post("/v1/build")
async def create_build(req: BuildRequest, auth: str = Depends(verify_api_key)):
    repo = req.repo
    created_repo = None
    if req.create_repo:
        if req.repo:
            raise HTTPException(status_code=400, detail="Provide either 'repo' or 'create_repo', not both.")
        if not req.create_repo.token:
            raise HTTPException(status_code=400, detail="create_repo requires a PAT (token)")
        if not REPO_NAME_RE.match(req.create_repo.name) or ".." in req.create_repo.name:
            raise HTTPException(
                status_code=400,
                detail="Invalid repo name: use 1-100 chars of letters, digits, '-', '_' or '.'; start with a letter or digit.",
            )
        client = GitHubRepoClient(owner="", repo="", token=req.create_repo.token)
        try:
            created_repo = await client.create_repo(
                req.create_repo.name, req.create_repo.private, req.create_repo.description
            )
        except GitHubError as e:
            status = e.status if 400 <= e.status < 500 else 502
            raise HTTPException(status_code=status, detail=f"GitHub repo creation failed: {e.body[:300]}")
        if not created_repo.get("owner") or not created_repo.get("name"):
            raise HTTPException(status_code=502, detail="GitHub repo creation returned an unexpected response")
        repo = RepoConfig(owner=created_repo["owner"], name=created_repo["name"], token=req.create_repo.token)

    build_id = await coordinator.submit(req.prompt, req.agents, req.token_budget, req.strategy, repo=repo)
    if created_repo:
        build = await store.load(build_id)
        if build and build.metadata.get("repo"):
            build.metadata["repo"]["created"] = True
            build.metadata["repo"]["html_url"] = created_repo["html_url"]
            await store.save(build)
    if req.slack_webhook:
        build = await store.load(build_id)
        build.metadata["slack_webhook"] = req.slack_webhook
        await store.save(build)
    return {
        "build_id": build_id,
        "state": "queued",
        "status_url": f"/v1/build/{build_id}",
        "websocket_url": f"/v1/build/{build_id}/stream",
        "estimated_duration": "120s",
        "repo": None if not repo else {"owner": repo.owner, "name": repo.name, "branch": repo.branch},
        "repo_created": created_repo["html_url"] if created_repo else None,
    }

@router.get("/v1/build/{build_id}")
async def get_build(build_id: str, auth: str = Depends(verify_api_key)):
    build = await store.load(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    return _build_summary(build)

@router.get("/v1/builds")
async def list_builds(limit: int = 50, offset: int = 0, auth: str = Depends(verify_api_key)):
    builds = await store.list(limit=limit, offset=offset)
    return {"builds": [_build_summary(b) for b in builds], "limit": limit, "offset": offset}

@router.post("/v1/build/{build_id}/respond")
async def respond(build_id: str, req: RespondRequest, auth: str = Depends(verify_api_key)):
    result = await coordinator.human_input(build_id, req.response)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/v1/build/{build_id}/cancel")
async def cancel(build_id: str, auth: str = Depends(verify_api_key)):
    build = await store.load(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    if build.state in [BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED]:
        raise HTTPException(status_code=400, detail="Build already terminal")
    build.state = BuildState.CANCELLED
    await store.save(build)
    return {"status": "cancelled", "build_id": build_id}
