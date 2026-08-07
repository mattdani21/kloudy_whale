# Railway deploy: verified live /v1/health + repeatable smoke-build script

## What this issue was about

M1 "Deploy publicly": the Railway deploy config (root `Dockerfile` + `railway.json` with `/v1/health` healthcheck) was staged but unverified. This PR verifies the live deployment and makes that verification repeatable.

## What changed

- **`scripts/verify-deploy.sh` (new)** — one command to prove the public instance is healthy and functional:
  - `GET /v1/health` must return 200 `{"status":"ok",...}` (no auth)
  - `GET /v1/config` reports whether `DEFAULT_GITHUB_TOKEN` is preloaded
  - With `APP_API_KEY` set in the environment (never hardcoded, never echoed): submits a real build (`create_repo` → private `kw-smoke-<ts>` repo), polls `/v1/build/<id>` to a terminal state, and asserts `completed` with a commit SHA.
- **`STATE.md`** — deploy is no longer "staged": documents the live URL, verification results (2026-08-07), enforced auth, and the E2E command/blocker.
- **`README.md`** — "Try the live instance" points at the verify script.

## Verification (live, 2026-08-07)

- `https://kloudywhale-production.up.railway.app/v1/health` → **HTTP 200** `{"status":"ok","version":"1.0.0"}` (no `x-railway-fallback`; routing healthy).
- Deployed `/` is **byte-identical** to `swarm-harness/app/static/index.html` on `main` → the live instance runs current main.
- `/v1/config` → `{"github_token_preloaded":true}` (Redis, model keys, PAT are set on the deployment).
- Auth is enforced: code-default `dev-key-change-me` is rejected with **401 Invalid API key** → the deployment has a custom `APP_API_KEY`.
- `scripts/verify-deploy.sh` passes health + config checks (exit 0); smoke build branch skipped without the key by design.
- Test gate: `cd swarm-harness && pytest -q` → **81/81 passed** (CI-identical command; deps preinstalled in the host gate env).

## Remaining for the milestone DoD

The real-build E2E against the deployed instance requires the deployment owner's `APP_API_KEY` (a credential this worker must not read or echo). One command once available:

```
APP_API_KEY=<owner key> scripts/verify-deploy.sh
```

It creates a private `kw-smoke-<ts>` repo and polls until the build completes. A real build (24,314 tokens, repo commit) previously completed against this same instance — see the railway-deployment skill postmortem.
