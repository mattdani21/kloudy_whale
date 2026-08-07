# Railway deploy verified — /v1/health live on the public URL

## What this PR does

Confirms the Railway deploy path (root `railway.json` + root `Dockerfile`) is
correct and working end to end, and proves the live public instance serves
`/v1/health`:

- **Live verification** — `https://kloudywhale-production.up.railway.app/v1/health`
  returns `HTTP 200 {"status":"ok","version":"1.0.0"}` (no auth required, as
  Railway's healthcheck needs). `scripts/verify-deploy.sh` passes all
  credential-free checks; `GET /v1/config` reports `github_token_preloaded: True`.
- **Auth enforced on prod** — `POST /v1/build` with the default
  `dev-key-change-me` key returns `401 Invalid API key`: the deploy has a custom
  `APP_API_KEY` set, so the dev default is not live.
- **railway.json is schema-valid** — validated against the official Railway
  schema (fetched with a browser UA; it 403s urllib's default one).
- **Dockerfile proven locally** — `docker build` from the repo root succeeds;
  running the image with `PORT=8080` (as Railway injects) serves
  `/v1/health` 200 on 8080 only, and SIGTERM produces a clean
  "Shutting down / Finished server process" (the `exec`'d CMD works).
- **Build context hygiene** — new `.dockerignore` keeps Railway's build
  context lean: previously every build uploaded `.git` + the 35 MB
  `.venv-test`; the image only needs `swarm-harness/{requirements.txt,app,worker}`.

## How it was tested

- `cd swarm-harness && pip install -r requirements.txt -r requirements-dev.txt && pytest -q`
  → **81 passed** (Python 3.13 venv, matches the recorded 81/81 baseline).
- `sh scripts/verify-deploy.sh` against the live URL → exit 0 (health 200,
  config 200).
- Docker: build OK; container bound `$PORT`; health 200; graceful shutdown on
  stop.

## Remaining handoff (owner access required)

The milestone DoD also wants a real build to complete against the deployed
instance. That needs the production `APP_API_KEY`, which only the owner has
(and which is deliberately not readable from this environment). One command
once available:

```
APP_API_KEY=... scripts/verify-deploy.sh
```

It creates a private `kw-smoke-<ts>` repo, submits a 4-agent swarm build, and
polls to a terminal state. The deployed instance is ready for it: auth
enforced, GitHub PAT preloaded, health green.
