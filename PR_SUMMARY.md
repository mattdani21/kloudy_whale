# Production env: APP_API_KEY (not dev-key-change-me), REDIS_URL, DEEPSEEK_API_KEY (+ KIMI_API_KEY, NOTIFICATION_WEBHOOK)

## What this PR does

Closes M1 "Deploy publicly" item 2: production deployments can no longer
silently run with dev-oriented, insecure configuration. The env vars named in
the issue (`APP_API_KEY`, `REDIS_URL`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY`,
`NOTIFICATION_WEBHOOK`) are read from the environment as before — the gap was
that a misconfigured deploy would boot anyway with a public default key and
fail confusingly at build time. Now it refuses to start, with an actionable
error.

- **Fail-fast production config validation** (`app/config.py`) — in production
  mode the app raises at import time (container exits immediately, message
  names the exact variable to fix) when any of these hold:
  - `APP_API_KEY` missing, or still the public dev default `dev-key-change-me`
  - `REDIS_URL` unset (the `redis://localhost:6379` default only fits local dev)
  - neither `DEEPSEEK_API_KEY` nor `KIMI_API_KEY` set (no agent could run)
  Development defaults are unchanged (tests, local dev, docker-compose).
- **Production mode detection** — `ENVIRONMENT=production`, or Railway is
  auto-detected (`RAILWAY_ENVIRONMENT` is always set on Railway deploys), so a
  Railway box can never boot with development defaults by accident.
- **`/v1/config` reports `production_mode`** (public, no secrets) so the live
  deployment's posture is verifiable; `scripts/verify-deploy.sh` prints it.
- **Deployment manifests wired** — docker-compose passes `ENVIRONMENT`
  (default `development`); the k8s manifest sets `ENVIRONMENT=production` and
  adds `APP_API_KEY` from `app-secrets`.
- **CI guards the shipped image** (`deploy-image` job): the `/v1/health` smoke
  now boots the container in production mode with complete config (proves the
  validation passes when configured right), and a new negative guard asserts
  the container **refuses to start** with the dev default key. No real
  secrets anywhere in CI.
- **README**: `ENVIRONMENT` config row, a "Production checklist" section
  under Deployment, and the "Current limitations" note updated (CORS `*` and
  the 7-day Redis TTL remain the open dev-oriented defaults).

## Verification

- Gate: `cd swarm-harness && pip install -r requirements.txt -r
  requirements-dev.txt && pytest -q` → **93 passed** (81 baseline + 12 new
  tests in `tests/test_config.py`: production detection incl. Railway,
  dev-key rejection, REDIS_URL/provider-key requirements, legacy `API_KEY`
  alias, and an import-time fail-fast integration test).
- Subprocess proof: `ENVIRONMENT=production` with no/`dev-key-change-me` key
  → `RuntimeError` listing all three problems; with a real key + `REDIS_URL` +
  provider key (incl. `RAILWAY_ENVIRONMENT` set) → boots, `production_mode`
  true.
- The live Railway instance already carries a custom `APP_API_KEY`,
  `REDIS_URL`, and DeepSeek/Kimi keys (STATE.md), so the production
  validation passes on the next deploy and `/v1/health` stays green;
  `/v1/config` will then report `production_mode: true`.

## Remaining for the milestone DoD

The real-build E2E against the deployed instance still needs the deployment
owner's `APP_API_KEY` (a credential this worker must not read or echo) —
unchanged blocker, documented in STATE.md:

```
APP_API_KEY=<owner key> scripts/verify-deploy.sh
```
