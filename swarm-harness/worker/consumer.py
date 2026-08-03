# worker/consumer.py
"""Background durability worker.

The API process runs builds in-process via asyncio.create_task; if the
container restarts (deploy, crash, OOM), those tasks are orphaned. This
worker is the safety net:

- Builds stuck in QUEUED (scheduled but never picked up) are run again.
- Builds stuck in a RUNNING state (planning/executing/reviewing/merging)
  past STALE_BUILD_TTL_MINUTES are reset to QUEUED and re-run (crash
  recovery). WAITING_HUMAN builds are NEVER touched — they are
  legitimately paused on a human gate.
"""
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List

from app.models import BuildState, SwarmBuild
from app.persistence import RedisStore
from app.swarm_coordinator import SwarmCoordinator
from app.config import CONFIG

logging.basicConfig(level=CONFIG.LOG_LEVEL)

def log_build_event(build_id: str, event: str, data: dict):
    logging.info(json.dumps({
        "build_id": build_id,
        "event": event,
        "timestamp": datetime.utcnow().isoformat(),
        **data
    }))

POLL_INTERVAL = 5  # seconds
RECENTLY_RESUMED_TTL = 30  # seconds: dedupe window against double-scheduling

# States that must eventually move forward — a crash can leave them stuck.
_RUNNING_STATES = {
    BuildState.PLANNING,
    BuildState.EXECUTING,
    BuildState.REVIEWING,
    BuildState.MERGING,
}


def classify_stale(builds: List[SwarmBuild], now: datetime = None, ttl_minutes: int = None) -> dict:
    """Split builds into {queued, stale_running}. Pure + testable.

    - queued: QUEUED builds (orphaned before pickup) -> resume immediately.
    - stale_running: RUNNING-state builds whose updated_at is older than the
      TTL -> reset to QUEUED and re-run. WAITING_HUMAN and terminal states
      are never included.
    """
    now = now or datetime.utcnow()
    ttl = timedelta(minutes=ttl_minutes if ttl_minutes is not None else int(CONFIG.STALE_BUILD_TTL_MINUTES))
    result = {"queued": [], "stale_running": []}
    for b in builds:
        if b.state == BuildState.QUEUED:
            result["queued"].append(b)
        elif b.state in _RUNNING_STATES:
            try:
                updated = datetime.fromisoformat(b.updated_at)
            except (ValueError, TypeError):
                continue  # unknown age -> leave alone, don't thrash
            if now - updated > ttl:
                result["stale_running"].append(b)
    return result


async def consume():
    store = RedisStore()
    coordinator = SwarmCoordinator()
    log_build_event("-", "worker_started", {"poll_interval": POLL_INTERVAL, "stale_ttl_minutes": int(CONFIG.STALE_BUILD_TTL_MINUTES)})
    recently_resumed = {}  # build_id -> timestamp of last schedule (dedupe)
    while True:
        try:
            builds = await store.list(limit=200)
            found = classify_stale(builds)
            to_run = []
            for build in found["queued"] + found["stale_running"]:
                if build.id in recently_resumed and (datetime.utcnow() - recently_resumed[build.id]).total_seconds() < RECENTLY_RESUMED_TTL:
                    continue  # already scheduled in the dedupe window
                if build.state in _RUNNING_STATES:
                    build.error_log.append(f"Crash recovery: reset {build.state.value} -> queued (stuck past TTL)")
                    build.state = BuildState.QUEUED
                    await store.save(build)
                    log_build_event(build.id, "recovering_stuck_build", {"from": "running"})
                else:
                    log_build_event(build.id, "resuming_queued_build", {"prompt": build.prompt[:100]})
                recently_resumed[build.id] = datetime.utcnow()
                to_run.append(build)
            for build in to_run:
                asyncio.create_task(coordinator._run(build))
            # prune dedupe map
            cutoff = datetime.utcnow() - timedelta(seconds=RECENTLY_RESUMED_TTL)
            recently_resumed = {k: v for k, v in recently_resumed.items() if v > cutoff}
        except Exception as e:
            logging.error(f"Worker poll failed: {e}")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(consume())
