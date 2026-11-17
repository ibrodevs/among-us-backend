"""Northflank command healthcheck; no database or secret output."""

import json
import os
import time
from pathlib import Path

value = json.loads(
    Path(
        os.getenv("WORKER_HEALTH_FILE", "/tmp/crewmate-x-worker-health.json")
    ).read_text()
)
assert time.time() - value["at"] < 15, "Clock heartbeat is stale"
os.kill(value["pid"], 0)
print("ok")
