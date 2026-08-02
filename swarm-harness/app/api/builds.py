# app/api/builds.py
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import List, Optional, Literal
from app.models import AgentConfig, BuildState, RepoConfig
from app.swarm_coordinator import SwarmCoordinator
from app.persistence import RedisStore
from app.config import CONFIG

router = APIRouter()

coordinator = SwarmCoordinator()
store = RedisStore()

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != CONFIG.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

class BuildRequest(BaseModel):
    prompt: str
    agents: List[AgentConfig]
    strategy: Literal["single", "swarm", "debate"] = "swarm"
    token_budget: int = 4000000
    slack_webhook: Optional[str] = None
    repo: Optional[RepoConfig] = None  # GitHub repo the build writes to

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
    build_id = await coordinator.submit(req.prompt, req.agents, req.token_budget, req.strategy, repo=req.repo)
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
        "repo": None if not req.repo else {"owner": req.repo.owner, "name": req.repo.name, "branch": req.repo.branch},
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
