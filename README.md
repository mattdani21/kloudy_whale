# DeepKimi — Persistent Agent Coding Platform

> **Deep**Seek × Ki**mi** (Moonshot): a persistent, cloud-hosted agent coding platform. Kick off a build from anywhere — laptop, phone, CI, chat — and a swarm of specialized LLM agents (planner, coders, reviewers, merger) plans, codes, reviews, and merges the deliverable for you, with human-in-the-loop gates, token budgeting, live streaming, and notifications to your channels.

DeepKimi is a **FastAPI-based agent orchestration platform** (codename *swarm-harness*) built to run **24/7 in the cloud**. You submit a build with one prompt; the system plans it, executes sub-tasks in parallel with agents drawn from DeepSeek and Kimi/Moonshot, cross-reviews the outputs, retries rejected work, merges everything into a final deliverable, and notifies you — all asynchronously, with full state persisted in Redis.

It is not a chat app, and it is not tied to your machine. It is a **persistent, API-first backend for running multi-agent "swarm" coding workflows** — the kind of service you deploy once, point your API keys at, and trigger from anywhere.

### The vision: persistent, kick off from anywhere

The goal is a cloud service that acts as a long-lived coding teammate:

- **Persistent** — build state lives in Redis, not in process memory. Builds survive API restarts, and the background worker re-runs any build orphaned by a crash, so nothing is lost.
- **Kick off from anywhere** — a single REST call is all it takes: `curl` from your phone, the CLI from your laptop, a step in a CI pipeline, a chat slash-command, or a webhook from any other system.
- **Stay in the loop from anywhere** — progress streams over WebSocket, completion/failure/pause events are pushed to your webhook or Slack, and when a build needs a human decision you answer over the API from whatever device you're on. The build *waits* for you, then resumes from its checkpoint.
- **Provider-agnostic swarm** — agents are declared per build (role + provider + model), so one platform drives DeepSeek, Kimi, or any mix of the two, per task.

Concrete ways to trigger a build:

| Where | How |
|---|---|
| Laptop | `python swarm-cli.py "…"` — interactive; answers human gates inline |
| Phone | `curl -X POST https://your-host/v1/build …` — watch the Slack/webhook notifications, answer gates with another `curl` |
| CI / cron | One `curl` in a pipeline step; poll or stream the result |
| Chat apps | Wrap `POST /v1/build` behind a slash-command or bot; get results via the Slack webhook |

The rest of this README documents the implementation as it exists today and how it maps to that vision.

---

## Table of Contents

- [The vision](#the-vision-persistent-kick-off-from-anywhere)
- [How it works](#how-it-works)
- [Key concepts](#key-concepts)
- [Project layout](#project-layout)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Live streaming (WebSocket)](#live-streaming-websocket)
- [CLI](#cli)
- [Notifications](#notifications)
- [Testing](#testing)
- [Deployment](#deployment)
- [Current limitations](#current-limitations)

---

## How it works

```
┌──────────┐   POST /v1/build    ┌───────────────────────┐   ┌────────────────┐
│  Client  │ ──────────────────▶ │  Swarm Coordinator    │──▶│ Notifications  │
│ (CLI/App)│ ◀────────────────── │  (async task runner)  │   │ (webhook/Slack)│
└──────────┘   GET /v1/build/:id └──────────┬────────────┘   └────────────────┘
        ▲            ◀── WebSocket stream ──┤
        │                                   ▼
        │                    ┌─────────────────────────────┐
        └── human answer ───▶│   LLM Router (aiohttp)      │
         (POST .../respond)  │  DeepSeek API │ Kimi API     │
                             └─────────────────────────────┘
                                        │
                             ┌──────────▼──────────┐
                             │  Redis (state store)│
                             └─────────────────────┘
```

Every build runs through a **four-phase pipeline** driven by `SwarmCoordinator` (`app/swarm_coordinator.py`):

### Phase 1 — Planning
A **planner** agent (typically DeepSeek) receives your prompt and returns a JSON array of sub-tasks, each tagged with a role (`coder` / `reviewer` / `tester`). A sub-task prefixed with `[HUMAN_INPUT]` flags that clarification is needed. The plan becomes the build's execution steps (max 5 parallel tasks per build).

### Phase 2 — Parallel execution
Pending steps are executed **concurrently** (`asyncio.gather`) by agents in the pool, each step routed to its configured provider/model with retry-on-transient-failure (exponential backoff). If **more than half** the swarm fails, the build fails fast. Token usage is tracked against the build's budget after every call.

### Phase 3 — Cross-review
A **reviewer** agent reviews every completed step's output and marks it approved or rejected. Any unapproved step is **retried once** (as long as the build has used less than 80% of its token budget).

### Phase 4 — Merge
A **merger** ("tech lead") agent combines all step outputs with the original prompt into the final deliverable (`final_output`), and the build transitions to `completed`.

### Human-in-the-loop
At any point the plan or a step can request clarification. The build enters `waiting_human`, fires a **high-urgency notification**, and **pauses** — the plan/checkpoint stays intact in Redis. You answer via `POST /v1/build/{id}/respond` (or the CLI prompts you interactively), the answer is folded into the paused step, and the build **resumes from its checkpoint** (planning is skipped on resume).

---

## Key concepts

| Concept | Description |
|---|---|
| **Build** | One unit of work: a prompt, a strategy, a list of agents, steps, token usage, and state. Identified by a 12-char hex `build_id`. |
| **Agent** | A role + provider + model + temperature + system prompt. Agents are declared per-build in the request. |
| **Step** | A single sub-task executed by one agent: prompt, result, review verdict, tokens used, duration, retry count, error. |
| **Strategy** | `swarm` (default), `single`, or `debate` — declared on the build; `swarm` is the implemented default pipeline. |
| **Token budget** | Per-build cap (default 50,000). Execution halts with an error once `token_usage >= token_budget_total`. |

### Agent roles (`AgentRole`)

`planner` → `coder` → `reviewer` → `merger` (plus `tester` and `tool`, declared for extensibility).

### Providers (`ModelProvider`)

| Provider | Endpoint | Default model |
|---|---|---|
| `deepseek` | `https://api.deepseek.com/v1/chat/completions` | `deepseek-v4-flash-ultra-reasoning` |
| `kimi` | `https://api.moonshot.cn/v1/chat/completions` | `kimi-k3` |

> **Fallback:** if `KIMI_API_KEY` is not set, any `kimi` agent silently routes to DeepSeek using `DEEPSEEK_FALLBACK_MODEL` (a warning is logged per request). This means a DeepSeek-only deployment works out of the box with the default agent lineup — Kimi is used only when its key is configured.

### Build lifecycle (`BuildState`)

```
queued → planning → executing → reviewing → merging → completed
              │            │            │
              ▼            ▼            ▼
          cancelled    waiting_human   failed
                         │  (resume)
                         ▼
                      executing
```

`completed`, `failed`, and `cancelled` are terminal. Every transition is validated against the state machine in `app/state_machine.py`; illegal transitions raise an error.

Builds are persisted to Redis under `swarm:build:{id}` with a **7-day TTL** (`app/persistence.py`).

---

## Project layout

```
DeepKimi/
├── Architecture Overview.md      # original design notes (rough, for reference)
└── swarm-harness/                # ← the actual application
    ├── app/
    │   ├── main.py               # FastAPI app: CORS, routers, /v1/health
    │   ├── config.py             # env-driven configuration (CONFIG singleton)
    │   ├── models.py             # enums + dataclasses (BuildState, AgentConfig, Step, SwarmBuild)
    │   ├── llm_router.py         # aiohttp client for DeepSeek/Kimi, tenacity retries, rate-limit lock
    │   ├── swarm_coordinator.py  # the orchestration engine (4-phase pipeline, human gate, resume)
    │   ├── agent_pool.py         # executes individual steps with budget enforcement
    │   ├── state_machine.py      # valid build-state transition table
    │   ├── persistence.py        # RedisStore: save / load / list builds (7-day TTL)
    │   ├── notifications.py      # generic webhook + per-build Slack notifications
    │   ├── tool_registry.py      # pluggable tool registry (currently placeholder tools)
    │   └── api/
    │       ├── builds.py         # REST endpoints (auth, build CRUD, respond, cancel)
    │       └── websocket.py      # live build stream over WebSocket
    ├── worker/
    │   └── consumer.py           # optional background worker: recovers orphaned QUEUED builds
    ├── tests/                    # pytest suite (API, coordinator, models, persistence, state machine)
    ├── swarm-cli.py              # interactive CLI: submit → poll → answer human gates → print result
    ├── Dockerfile                # python:3.11-slim + uvicorn (2 workers)
    ├── docker-compose.yml        # redis + api, ready to go
    ├── k8s-deployment.yaml       # Kubernetes Deployment + LoadBalancer Service
    ├── requirements.txt          # runtime deps
    └── requirements-dev.txt      # test deps
```

**Execution model:** builds run **in-process** — `submit()` saves the build to Redis, then fires `asyncio.create_task(self._run(build))` and returns the id immediately. The optional worker (`worker/consumer.py`) is a **durability safety net**: it polls for builds stuck in `queued` (e.g. orphaned by an API restart) and re-runs them.

---

## Quick start

### Option A — Docker Compose (recommended)

```bash
cd swarm-harness
export DEEPSEEK_API_KEY=sk-...        # required for DeepSeek agents
export KIMI_API_KEY=sk-...            # required for Kimi agents
export API_KEY=change-me             # auth key for the API (default: dev-key-change-me)
docker compose up --build
```

- API: http://localhost:8000 (health check: `GET /v1/health`)
- Redis: `localhost:6379`

### Option B — Local development

Requires **Python 3.11+** and a running **Redis 7** (any reachable instance; the default is `redis://localhost:6379`).

```bash
cd swarm-harness
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-...
export KIMI_API_KEY=sk-...
uvicorn app.main:app --reload
```

### Smoke test

```bash
curl http://localhost:8000/v1/health
# {"status":"ok","version":"1.0.0"}
```

---

## Configuration

All configuration is environment-driven (`app/config.py`).

| Variable | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | *(empty)* | API key for DeepSeek (`api.deepseek.com`) |
| `KIMI_API_KEY` | *(empty)* | API key for Kimi/Moonshot (`api.moonshot.cn`). If unset, `kimi` agents automatically **fall back to DeepSeek** (`DEEPSEEK_FALLBACK_MODEL`) instead of failing |
| `DEEPSEEK_FALLBACK_MODEL` | `deepseek-v4-flash-ultra-reasoning` | Model used when a `kimi` agent runs without `KIMI_API_KEY` |
| `API_KEY` | `dev-key-change-me` | Shared secret required in the `X-API-Key` header on every request. **Change it before any non-local deployment.** |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `MAX_STEPS` | `25` | Reserved upper bound for build steps |
| `DEFAULT_TOKEN_BUDGET` | `50000` | Default per-build token budget |
| `NOTIFICATION_WEBHOOK` | *(empty)* | Generic webhook URL receiving build events |
| `LOG_LEVEL` | `INFO` | Logging level (used by the worker) |

---

## API reference

All routes except `GET /v1/health` require the header `X-API-Key: <API_KEY>`.

### `POST /v1/build` — submit a build

**Body:**

```json
{
  "prompt": "Build a FastAPI todo app with SQLite persistence",
  "agents": [
    {"role": "planner",  "provider": "deepseek", "model": "deepseek-chat"},
    {"role": "coder",    "provider": "kimi",     "model": "kimi-k3"},
    {"role": "reviewer", "provider": "deepseek", "model": "deepseek-chat"},
    {"role": "merger",   "provider": "kimi",     "model": "kimi-k3"}
  ],
  "strategy": "swarm",
  "token_budget": 50000,
  "slack_webhook": "https://hooks.slack.com/services/..."
}
```

- `agents` — **required**; each entry: `role` (`planner|coder|reviewer|tester|merger|tool`), `provider` (`deepseek|kimi`), `model`, plus optional `temperature`, `max_tokens`, `system_prompt`, `token_budget`.
- `strategy` — `single` | `swarm` (default) | `debate`.
- `slack_webhook` — optional; per-build Slack notifications.

**Response:**

```json
{
  "build_id": "a1b2c3d4e5f6",
  "state": "queued",
  "status_url": "/v1/build/a1b2c3d4e5f6",
  "websocket_url": "/v1/build/a1b2c3d4e5f6/stream",
  "estimated_duration": "120s"
}
```

```bash
curl -X POST http://localhost:8000/v1/build \
  -H "X-API-Key: dev-key-change-me" -H "Content-Type: application/json" \
  -d '{"prompt":"Write a hello-world CLI in Python","agents":[{"role":"planner","provider":"deepseek","model":"deepseek-chat"},{"role":"coder","provider":"kimi","model":"kimi-k3"},{"role":"reviewer","provider":"deepseek","model":"deepseek-chat"},{"role":"merger","provider":"kimi","model":"kimi-k3"}]}'
```

### `GET /v1/build/{build_id}` — status & result

Returns the build summary: state, token usage/budget, whether human input is needed (and the pending question), per-step status, error log, and `final_output` when complete.

### `GET /v1/builds?limit=50&offset=0` — list builds

Returns a paginated summary of recent builds (from Redis, so recent runs only).

### `POST /v1/build/{build_id}/respond` — answer a human gate

```json
{"response": "Use PostgreSQL instead of SQLite"}
```

Only valid while the build is `waiting_human`; otherwise `400`. Returns `{"status": "resumed", "build_id": "..."}`.

### `POST /v1/build/{build_id}/cancel` — cancel a build

Cancels non-terminal builds. Returns `{"status": "cancelled", "build_id": "..."}`.

---

## Live streaming (WebSocket)

Connect to `/v1/build/{build_id}/stream?api_key=<API_KEY>` to receive a JSON status snapshot every ~2 seconds:

```json
{
  "build_id": "a1b2c3d4e5f6",
  "state": "executing",
  "token_usage": 1234,
  "steps_done": 2,
  "steps_total": 4,
  "needs_human": false,
  "human_question": null,
  "final_output": null
}
```

The server closes the socket when the build reaches a terminal state (and sends `final_output` on completion). Close codes: `4401` = bad API key, `4404` = build not found.

---

## CLI

The interactive CLI (`swarm-cli.py`) is the fastest way to try the system end-to-end: it submits a default 4-agent build (planner/reviewer on DeepSeek, coder/merger on Kimi, 40k token budget — coder/merger fall back to DeepSeek automatically if no Kimi key is set), polls until done, **prompts you inline when a human gate fires**, and prints the final output.

```bash
export SWARM_API_URL=http://localhost:8000   # default
export API_KEY=dev-key-change-me             # default
python swarm-cli.py "Write a Python script that renames all .txt files in a folder"
```

---

## Notifications

`NotificationDispatcher` (`app/notifications.py`) sends build events with: `build_id`, `state`, `message`, `urgency`, `needs_human`, token usage/budget, and a 500-char preview of `final_output`.

- **Generic webhook** — set `NOTIFICATION_WEBHOOK` (receives the full JSON payload).
- **Slack** — pass a `slack_webhook` per build (or per agent metadata); posts a formatted message with status emoji.

Events you'll see: 🛑 build paused for human input (high urgency), ❌ swarm failed (high urgency), ✅ swarm complete (normal).

---

## Testing

```bash
cd swarm-harness
pip install -r requirements-dev.txt
pytest
```

The suite covers the API surface (auth, submit, list, respond, cancel — using fake store/coordinator), coordinator behavior, model serialization, Redis persistence round-trips, and the state machine's transition rules. No live LLM calls or Redis required.

---

## Deployment

The whole point is a service that stays up: deploy once, keep it running, trigger builds from anywhere. Pick the option that matches your budget:

- **Docker Compose** — `docker compose up --build` (Redis + API, env passthrough for keys). Good for a single node — a $5–10 VPS runs this comfortably.
- **Kubernetes** — `k8s-deployment.yaml`: 3-replica Deployment (secrets via `app-secrets`), LoadBalancer Service. Swap `your-registry/swarm-harness:latest` for your image.
- **Managed platforms** — the design notes (`Architecture Overview.md`) discuss Railway/Render, AWS Lambda + EventBridge, Google Cloud Run + Cloud Tasks, Hetzner/DigitalOcean VPS, and Fly.io. For anything multi-instance, remember: **builds execute in-process**, so run the `worker/consumer.py` recovery loop alongside the API to pick up builds orphaned by restarts (it re-runs any build left in `queued`).

---

## Current limitations

The codebase is an early implementation of the vision above. Known gaps:

- **In-process execution** — builds live and die with the API process; the worker only rescues builds still in `queued`. For hard durability across crashes, an out-of-process queue (e.g. Celery/Redis Streams) is the natural next step.
- **Placeholder tools** — `tool_registry.py` ships with stub implementations (`write_file`, `read_file`, `execute_python`, `web_search`); they log/return placeholders rather than performing real actions. Wire them to real storage/execution/search backends before relying on them.
- **Defaults are dev-oriented** — CORS allows all origins, the API key defaults to `dev-key-change-me`, and builds expire from Redis after 7 days. Harden all three before production.
- **Plan cap** — a build executes at most 5 sub-tasks from the planner's plan.
- **Retries** — unapproved steps are retried at most once; the failure mode for a majority-failed swarm is fail-fast.
- **Rate limiting** — the LLM router serializes calls with a single lock; there is no per-provider throughput management or queue yet.
