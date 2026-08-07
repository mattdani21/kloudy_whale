# Railway deploy: verified live /v1/health + repeatable smoke-build script

## What this PR does

Closes M1 "Deploy publicly" item 1: the Railway deploy path (root
`railway.json` + root `Dockerfile`) is verified against the live public
instance, and the verification is now repeatable in one command.

- **`scripts/verify-deploy.sh` (new)** — one command to prove the public
  instance is healthy and functional:
  - `GET /v1/health` must return 200 `{"status":"ok",...}` (no auth, as
    Railway's healthcheck needs)
  - `GET /v1/config` reports whether `DEFAULT_GITHUB_TOKEN` is preloaded
  - With `APP_API_KEY` set in the environment (never hardcoded, never
    echoed): submits a real build (`create_repo` → private `kw-smoke-<ts>`
    repo), polls `/v1/build/<id>` to a terminal state, and asserts
    `completed` with a commit SHA.
- **`.dockerignore` (new)** — Railway's build context previously included
  `.git` + the 35 MB `.venv-test`; the image only needs
  `swarm-harness/{requirements.txt,app,worker}`, so everything else is now
  excluded from context uploads. `.env` / `.env.*` are also excluded so local
  secrets can never land in an image layer.
- **CI guards the deploy artifact (new)** — `deploy-image` job in
  `.github/workflows/ci.yml` builds the root Dockerfile on every push/PR and
  smoke-tests `/v1/health` inside the running container (Railway-style `PORT`,
  unreachable `REDIS_URL` to prove health does not depend on Redis) — the same
  probe the live instance passes.
- **`STATE.md`** — deploy is no longer "staged": documents the live URL,
  verification results (2026-08-07), enforced auth, and the E2E
  command/blocker. (Also restores the `## Run command` section that a draft
  edit had dropped.)
- **`README.md`** — "Try the live instance" points at the verify script.

## Verification (live, 2026-08-07)

- `https://kloudywhale-production.up.railway.app/v1/health` → **HTTP 200**
  `{"status":"ok","version":"1.0.0"}`; `scripts/verify-deploy.sh` exits 0.
- Deployed `/` is **byte-identical** to `swarm-harness/app/static/index.html`
  on `main` → the live instance runs current main.
- `/v1/config` → `{"github_token_preloaded":true}` (Redis, model keys, PAT
  are set on the deployment).
- Auth is enforced: code-default `dev-key-change-me` is rejected with
  **401 Invalid API key** → the deployment has a custom `APP_API_KEY`.
- `railway.json` validated against the official Railway schema (fetched with
  a browser UA; it 403s urllib's default one) — DOCKERFILE builder,
  `/v1/health` healthcheck, ON_FAILURE restart.
- Dockerfile proven locally: `docker build` from repo root succeeds; running
  the image with `PORT=8080` (as Railway injects) serves `/v1/health` 200 on
  8080 only, and SIGTERM produces a clean "Shutting down / Finished server
  process" (the `exec`'d `$PORT` CMD works).

## How it was tested

- `cd swarm-harness && pip install -r requirements.txt -r requirements-dev.txt && pytest -q`
  → **81 passed** (Python 3.13 venv, matches the recorded 81/81 baseline).
- `sh scripts/verify-deploy.sh` against the live URL → exit 0 (health 200,
  config 200).
- Docker: build OK; container bound `$PORT`; health 200; graceful shutdown.

## Remaining for the milestone DoD

The real-build E2E against the deployed instance requires the deployment
owner's `APP_API_KEY` (a credential this worker must not read or echo). One
command once available:

```
APP_API_KEY=<owner key> scripts/verify-deploy.sh
```

It creates a private `kw-smoke-<ts>` repo, submits a 4-agent swarm build
(planner → coder → reviewer → merger), and polls to a terminal state. The
deployed instance is ready for it: auth enforced, GitHub PAT preloaded,
health green.
