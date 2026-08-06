# State

_Working FastAPI swarm harness (DeepKimi) with staged deploy config; not yet public._

## Current state

- Full multi-agent build pipeline in swarm-harness/: planner → parallel coders (`asyncio.gather`) → cross-review with one retry → repo write + verify → merge; human gates pause/resume via Redis checkpoints (README "How it works"; app/swarm_coordinator.py).
- Tests: 10 files in swarm-harness/tests (api, coordinator, worker, state machine, persistence, github client, llm router, agent pool, models, tool registry). CI runs `pytest -q` from swarm-harness (.github/workflows/ci.yml).
- Deploy config staged: root Dockerfile (Railway, single uvicorn worker), railway.json with /v1/health healthcheck, swarm-harness/docker-compose.yml (Redis + API), k8s-deployment.yaml.
- Token budgets exist in config: DEFAULT_TOKEN_BUDGET (4M), DAILY_TOKEN_BUDGET, MAX_CONCURRENT_BUILDS, LLM_CONCURRENCY (app/config.py).

## Broken / incomplete

- In-process execution: builds live and die with the API process; worker/consumer.py only rescues builds still in `queued` (README "Current limitations").
- execute_python and web_search tools are not implemented — app/tool_registry.py registers only read_file/list_files/write_file/commit, all repo-bound.
- Dev-oriented defaults: CORS allows all origins, API key defaults to `dev-key-change-me` (app/config.py:17), builds expire from Redis after 7 days (README).
- Single-lock LLM serialization in app/llm_router.py; no per-provider rate limiting.
- No landing page, no billing, no user accounts (single API-key auth); no open issues tracking these.

## Blockers

- None recorded (no open issues). Needed before public launch: production API keys, hosting decision (Railway per railway.json is staged), and the human gate on deploying publicly.

## Test command

`cd swarm-harness && pip install -r requirements-dev.txt && pytest -q` (matches CI: .github/workflows/ci.yml).

## Run command

`docker compose up --build` in swarm-harness/ (Redis + API on :8000, README "Deployment"), or `uvicorn app.main:app --port 8000` with REDIS_URL set (app/config.py).
