# State

_Deployed publicly on Railway: https://kloudywhale-production.up.railway.app — /v1/health verified 200 on 2026-08-07; auth enforced (custom APP_API_KEY, default dev-key-change-me rejected with 401)._

## Current state

- Full multi-agent build pipeline in swarm-harness/: planner → parallel coders (`asyncio.gather`) → cross-review with one retry → repo write + verify → merge; human gates pause/resume via Redis checkpoints (README "How it works"; app/swarm_coordinator.py).
- Tests: 10 files in swarm-harness/tests (api, coordinator, worker, state machine, persistence, github client, llm router, agent pool, models, tool registry). CI runs `pytest -q` from swarm-harness (.github/workflows/ci.yml).
- **Live on Railway**: root Dockerfile (single uvicorn worker, binds `$PORT`), railway.json with /v1/health healthcheck. Deployed instance serves current main (health `{"status":"ok","version":"1.0.0"}`, `/` byte-identical to swarm-harness/app/static/index.html), Redis + DeepSeek/Kimi keys + `DEFAULT_GITHUB_TOKEN` set (`/v1/config` reports `github_token_preloaded: true`). `scripts/verify-deploy.sh` re-verifies health/config and runs a real smoke build when `APP_API_KEY` is provided.
- Token budgets exist in config: DEFAULT_TOKEN_BUDGET (4M), DAILY_TOKEN_BUDGET, MAX_CONCURRENT_BUILDS, LLM_CONCURRENCY (app/config.py).
- **Production env guard (issue #5)**: production mode (`ENVIRONMENT=production`, or Railway auto-detected via `RAILWAY_ENVIRONMENT`) fails fast at startup with an actionable error when `APP_API_KEY` is missing or still the dev default `dev-key-change-me`, `REDIS_URL` is unset, or no LLM provider key (`DEEPSEEK_API_KEY`/`KIMI_API_KEY`) is configured (app/config.py). `/v1/config` now reports `production_mode` (public, no secrets). CI has a fail-fast guard that boots the shipped image in production mode and asserts it refuses to start with the dev key.

## Broken / incomplete

- In-process execution: builds live and die with the API process; worker/consumer.py only rescues builds still in `queued` (README "Current limitations").
- execute_python and web_search tools are not implemented — app/tool_registry.py registers only read_file/list_files/write_file/commit, all repo-bound.
- Dev-oriented defaults: CORS allows all origins, and builds expire from Redis after 7 days (README). The API key's dev default `dev-key-change-me` is now refused at startup in production mode — but CORS `*` and the 7-day Redis TTL still need hardening for full production posture (separate roadmap items).
- Single-lock LLM serialization in app/llm_router.py; no per-provider rate limiting.
- No landing page, no billing, no user accounts (single API-key auth); no open issues tracking these.

## Blockers

- End-to-end smoke build against the deployed instance needs the deployment owner's `APP_API_KEY` (401 with the code default). Command once available: `APP_API_KEY=<owner key> scripts/verify-deploy.sh`. Everything else about the deploy is verified.

## Test command

`cd swarm-harness && pip install -r requirements.txt -r requirements-dev.txt && pytest -q` (matches CI: .github/workflows/ci.yml)

> Verified 2026-08-06 (orchestrator Step-4): 81/81 pass, no Redis/API keys needed (in-memory fakes).
> Verified 2026-08-07 (issue #5, production env): 93/93 pass — 12 new tests in tests/test_config.py (production validation); test_api updated for the `production_mode` field.
> Note: `requirements-dev.txt` alone is NOT enough — tests import fastapi/redis from `requirements.txt`..

## Run command

`docker compose up --build` in swarm-harness/ (Redis + API on :8000, README "Deployment"), or `uvicorn app.main:app --port 8000` with REDIS_URL set (app/config.py).
