# tests/test_worker.py
from datetime import datetime, timedelta

from app.models import BuildState, SwarmBuild
from worker.consumer import classify_stale


def _build(bid: str, state: BuildState, age_minutes: float = 0) -> SwarmBuild:
    b = SwarmBuild(id=bid, prompt="p", state=state)
    b.updated_at = (datetime.utcnow() - timedelta(minutes=age_minutes)).isoformat()
    return b


def test_queued_builds_are_returned_immediately():
    builds = [_build("q1", BuildState.QUEUED)]
    found = classify_stale(builds, ttl_minutes=15)
    assert [b.id for b in found["queued"]] == ["q1"]
    assert found["stale_running"] == []


def test_stale_running_build_reset_candidate():
    builds = [_build("s1", BuildState.EXECUTING, age_minutes=30)]
    found = classify_stale(builds, ttl_minutes=15)
    assert [b.id for b in found["stale_running"]] == ["s1"]
    assert found["queued"] == []


def test_fresh_running_build_is_untouched():
    builds = [_build("f1", BuildState.EXECUTING, age_minutes=5)]
    found = classify_stale(builds, ttl_minutes=15)
    assert found["queued"] == []
    assert found["stale_running"] == []


def test_all_running_states_covered():
    for state in (BuildState.PLANNING, BuildState.EXECUTING, BuildState.REVIEWING, BuildState.MERGING):
        builds = [_build("x", state, age_minutes=60)]
        found = classify_stale(builds, ttl_minutes=15)
        assert len(found["stale_running"]) == 1, f"{state} should be recoverable"


def test_waiting_human_never_touched():
    builds = [_build("h1", BuildState.WAITING_HUMAN, age_minutes=999)]
    found = classify_stale(builds, ttl_minutes=15)
    assert found["queued"] == []
    assert found["stale_running"] == []


def test_terminal_states_never_touched():
    for state in (BuildState.COMPLETED, BuildState.FAILED, BuildState.CANCELLED):
        builds = [_build("t", state, age_minutes=999)]
        found = classify_stale(builds, ttl_minutes=15)
        assert found["queued"] == [] and found["stale_running"] == [], state


def test_unknown_age_left_alone():
    b = _build("u1", BuildState.EXECUTING)
    b.updated_at = "not-a-date"
    found = classify_stale([b], ttl_minutes=15)
    assert found["stale_running"] == []
