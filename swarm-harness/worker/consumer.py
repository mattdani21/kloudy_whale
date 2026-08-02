# worker/consumer.py
"""Optional background worker.

Picks up builds stuck in QUEUED state (e.g. after an API process restart
orphaned their asyncio tasks) and runs them through the swarm coordinator.
The API process runs builds in-process via asyncio.create_task; this worker
is a safety net for durability, not the primary execution path.
"""
import asyncio
import logging
import json
from datetime import datetime

from app.models import BuildState
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

async def consume():
    store = RedisStore()
    coordinator = SwarmCoordinator()
    log_build_event("-", "worker_started", {"poll_interval": POLL_INTERVAL})
    while True:
        try:
            builds = await store.list(limit=100)
            for build in builds:
                if build.state == BuildState.QUEUED:
                    log_build_event(build.id, "resuming_queued_build", {"prompt": build.prompt[:100]})
                    asyncio.create_task(coordinator._run(build))
        except Exception as e:
            logging.error(f"Worker poll failed: {e}")
        await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    asyncio.run(consume())
