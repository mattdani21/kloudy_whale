import pytest
from fastapi.testclient import TestClient

from app.config import CONFIG
from app.main import app
from app.api import builds as builds_module
from app.models import BuildState, SwarmBuild

API_KEY_HEADER = {"X-API-Key": CONFIG.API_KEY}

class FakeStore:
    def __init__(self):
        self.builds = {}

    async def save(self, build):
        self.builds[build.id] = build

    async def load(self, build_id):
        return self.builds.get(build_id)

    async def list(self, limit=50, offset=0):
        return list(self.builds.values())[offset:offset + limit]

class FakeCoordinator:
    def __init__(self, store):
        self.store = store
        self.submitted = []

    async def submit(self, prompt, agents, token_budget=50000, strategy="swarm"):
        build = SwarmBuild(id="testbuild123", prompt=prompt, state=BuildState.QUEUED,
                           strategy=strategy, agents=agents, token_budget_total=token_budget)
        await self.store.save(build)
        self.submitted.append(build)
        return build.id

    async def human_input(self, build_id, response):
        build = await self.store.load(build_id)
        if not build or build.state != BuildState.WAITING_HUMAN:
            return {"error": "Build not found or not waiting for input"}
        return {"status": "resumed", "build_id": build_id}

@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    store = FakeStore()
    coordinator = FakeCoordinator(store)
    monkeypatch.setattr(builds_module, "store", store)
    monkeypatch.setattr(builds_module, "coordinator", coordinator)
    return store, coordinator

@pytest.fixture
def client():
    return TestClient(app)

BUILD_BODY = {
    "prompt": "Build a hello world API",
    "agents": [
        {"role": "planner", "provider": "deepseek", "model": "deepseek-chat"},
        {"role": "coder", "provider": "kimi", "model": "kimi-k3"},
        {"role": "reviewer", "provider": "deepseek", "model": "deepseek-chat"},
        {"role": "merger", "provider": "kimi", "model": "kimi-k3"},
    ],
    "token_budget": 40000,
}

def test_health_no_auth(client):
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "1.0.0"}

def test_create_build_requires_auth(client):
    assert client.post("/v1/build", json=BUILD_BODY).status_code in (401, 422)
    resp = client.post("/v1/build", json=BUILD_BODY, headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401

def test_create_build(client, fakes):
    store, coordinator = fakes
    resp = client.post("/v1/build", json=BUILD_BODY, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["build_id"] == "testbuild123"
    assert data["state"] == "queued"
    assert data["status_url"] == "/v1/build/testbuild123"

    build = coordinator.submitted[0]
    assert build.prompt == BUILD_BODY["prompt"]
    assert len(build.agents) == 4
    assert build.agents[0].role.value == "planner"
    assert build.agents[1].provider.value == "kimi"
    assert build.token_budget_total == 40000

def test_create_build_with_slack_webhook(client, fakes):
    store, _ = fakes
    body = {**BUILD_BODY, "slack_webhook": "https://hooks.slack.com/x"}
    resp = client.post("/v1/build", json=body, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    build = store.builds["testbuild123"]
    assert build.metadata["slack_webhook"] == "https://hooks.slack.com/x"

def test_get_build(client, fakes):
    store, _ = fakes
    store.builds["b1"] = SwarmBuild(id="b1", prompt="p", state=BuildState.EXECUTING, token_usage=7)
    resp = client.get("/v1/build/b1", headers=API_KEY_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "b1"
    assert data["state"] == "executing"
    assert data["token_usage"] == 7
    assert data["needs_human"] is False

def test_get_build_404(client):
    assert client.get("/v1/build/missing", headers=API_KEY_HEADER).status_code == 404

def test_list_builds(client, fakes):
    store, _ = fakes
    for i in range(3):
        store.builds[f"b{i}"] = SwarmBuild(id=f"b{i}", prompt="p", state=BuildState.QUEUED)
    resp = client.get("/v1/builds", headers=API_KEY_HEADER)
    assert resp.status_code == 200
    assert len(resp.json()["builds"]) == 3

def test_respond_waiting_build(client, fakes):
    store, _ = fakes
    store.builds["b1"] = SwarmBuild(id="b1", prompt="p", state=BuildState.WAITING_HUMAN)
    resp = client.post("/v1/build/b1/respond", json={"response": "use postgres"}, headers=API_KEY_HEADER)
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"

def test_respond_non_waiting_build_400(client, fakes):
    store, _ = fakes
    store.builds["b1"] = SwarmBuild(id="b1", prompt="p", state=BuildState.EXECUTING)
    resp = client.post("/v1/build/b1/respond", json={"response": "hi"}, headers=API_KEY_HEADER)
    assert resp.status_code == 400

def test_cancel_build(client, fakes):
    store, _ = fakes
    store.builds["b1"] = SwarmBuild(id="b1", prompt="p", state=BuildState.EXECUTING)
    resp = client.post("/v1/build/b1/cancel", headers=API_KEY_HEADER)
    assert resp.status_code == 200
    assert store.builds["b1"].state == BuildState.CANCELLED

def test_cancel_terminal_build_400(client, fakes):
    store, _ = fakes
    store.builds["b1"] = SwarmBuild(id="b1", prompt="p", state=BuildState.COMPLETED)
    assert client.post("/v1/build/b1/cancel", headers=API_KEY_HEADER).status_code == 400

def test_cancel_missing_404(client):
    assert client.post("/v1/build/missing/cancel", headers=API_KEY_HEADER).status_code == 404
