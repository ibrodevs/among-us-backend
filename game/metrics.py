"""Opt-in local aggregate telemetry. Never stores identities, payloads or tokens."""

import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

_ENABLED = os.getenv("GAME_METRICS_ENABLED", "false").lower() == "true"
_SAMPLES = defaultdict(lambda: deque(maxlen=6000))
_COUNTS = defaultdict(int)
_WRITTEN = 0


def record(name, value):
    if _ENABLED:
        _SAMPLES[name].append(float(value))


def count(name, amount=1):
    if _ENABLED:
        _COUNTS[name] += amount


def flush(role, **extra):
    global _WRITTEN
    if not _ENABLED:
        return
    now = time.monotonic()
    if now - _WRITTEN < 1:
        return
    _WRITTEN = now
    stats = {}
    for name, values in list(_SAMPLES.items()):
        data = sorted(values)
        if data:
            stats[name] = {
                "n": len(data),
                "mean": sum(data) / len(data),
                "p95": data[int((len(data) - 1) * 0.95)],
                "p99": data[int((len(data) - 1) * 0.99)],
            }
    path = Path(os.getenv("GAME_METRICS_DIR", "/tmp")) / f"crewmate-x-{role}.json"
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(
                dict(
                    at=time.time(),
                    pid=os.getpid(),
                    stats=stats,
                    counts=dict(_COUNTS),
                    **extra,
                )
            )
        )
        temp.replace(path)
    except OSError:
        pass


def timed(name):
    from functools import wraps

    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            began = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                record(name, (time.monotonic() - began) * 1000)

        return run

    return decorate
