#!/bin/sh
# verify-deploy.sh — prove the public kloudy_whale Railway instance is healthy
# and that a real build completes against it.
#
# Usage:
#   scripts/verify-deploy.sh                      # health + config checks only
#   APP_API_KEY=... scripts/verify-deploy.sh      # + real smoke build (creates a
#                                                 #   private kw-smoke-<ts> repo)
#
# The API key is read from the environment ONLY — it is never hardcoded, logged,
# or echoed. BASE_URL and SMOKE_REPO_NAME are overridable for other deployments.
#
# Exit codes: 0 = everything checked passed, 1 = a check failed,
#             2 = usage/precondition error.
set -u

BASE_URL="${BASE_URL:-https://kloudywhale-production.up.railway.app}"
SMOKE_REPO_NAME="${SMOKE_REPO_NAME:-kw-smoke-$(date +%Y%m%d-%H%M%S)}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "== kloudy_whale deploy verification =="
echo "target: $BASE_URL"

# --- 1. /v1/health must answer 200 with status ok (no auth required) ---------
code=$(curl -sS -m 20 -o "$TMP/health.json" -w '%{http_code}' "$BASE_URL/v1/health") \
  || fail "health probe failed (network error?)"
echo "GET /v1/health -> HTTP $code"
[ "$code" = "200" ] || fail "health returned HTTP $code (want 200)"
grep -q '"status":"ok"' "$TMP/health.json" || fail "health body missing status ok: $(cat "$TMP/health.json")"
echo "body: $(cat "$TMP/health.json")"

# --- 2. /v1/config is public and tells us if a GitHub PAT is preloaded -------
code=$(curl -sS -m 20 -o "$TMP/config.json" -w '%{http_code}' "$BASE_URL/v1/config") \
  || fail "config probe failed"
echo "GET /v1/config -> HTTP $code"
[ "$code" = "200" ] || fail "config returned HTTP $code (want 200)"
python3 - "$TMP/config.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("github_token_preloaded:", d.get("github_token_preloaded"))
PY

# --- 3. Optional real build against the deployed instance --------------------
if [ -z "${APP_API_KEY:-}" ]; then
    echo
    echo "SKIP: smoke build not run (set APP_API_KEY to run it, e.g.)"
    echo "  APP_API_KEY=... $0"
    echo "It creates a private repo '$SMOKE_REPO_NAME' and polls until the build"
    echo "reaches a terminal state. The key is only read from the environment."
    exit 0
fi

echo
echo "== smoke build =="
echo "create_repo: $SMOKE_REPO_NAME (private)"
BODY=$(printf '%s' \
  '{"prompt":"Create a single README.md in the repo root. Content: a first line \"# '"$SMOKE_REPO_NAME"'\" and one short paragraph: \"Deploy smoke test for the kloudy_whale Railway instance.\" Nothing else.","agents":[{"role":"planner","provider":"kimi","model":"kimi-k3"},{"role":"coder","provider":"deepseek","model":"deepseek-v4-flash"},{"role":"reviewer","provider":"kimi","model":"kimi-k3"},{"role":"merger","provider":"deepseek","model":"deepseek-v4-flash"}],"strategy":"swarm","token_budget":50000,"create_repo":{"name":"'"$SMOKE_REPO_NAME"'","private":true,"description":"kloudy_whale deploy smoke test"}}') \
  || fail "failed to build request body"
resp=$(curl -sS -m 30 -X POST "$BASE_URL/v1/build" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APP_API_KEY" \
  -d "$BODY") || fail "build submit failed"
build_id=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("build_id",""))' 2>/dev/null)
if [ -z "$build_id" ]; then
    fail "build submit did not return a build_id; response: $resp"
fi
echo "build_id: $build_id"

i=0
while [ "$i" -lt 60 ]; do
    i=$((i + 1))
    sleep 10
    state=$(curl -sS -m 20 "$BASE_URL/v1/build/$build_id" \
      -H "X-API-Key: $APP_API_KEY" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state","?"))' 2>/dev/null)
    echo "  poll $i: state=$state"
    case "$state" in
        completed) break ;;
        failed|cancelled) fail "build ended in state '$state' — see GET /v1/build/$build_id" ;;
        "") fail "poll returned no state (network/API error)" ;;
    esac
done
[ "$state" = "completed" ] || fail "build not terminal after 10 min (last state: $state)"

curl -sS -m 20 "$BASE_URL/v1/build/$build_id" -H "X-API-Key: $APP_API_KEY" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("commit_sha:", d.get("commit_sha")); print("repo:", (d.get("repo") or {}).get("html_url", "n/a")); print("token_usage:", d.get("token_usage"))' \
  || fail "could not parse final build summary"
echo "OK: real build completed against $BASE_URL"
