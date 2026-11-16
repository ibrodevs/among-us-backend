"""Versioned geometry shared byte-for-byte with the frontend."""

import json
import math
from pathlib import Path

MAP = json.loads(Path(__file__).with_name("map.json").read_text())
TASKS = {task["point"]: task for task in MAP["tasks"]}


def blocked(x, y, geometry=None, doors=()):
    geometry = geometry or MAP
    half = geometry["player_hitbox"] / 2
    if (
        x - half < 0
        or y - half < 0
        or x + half > geometry["width"]
        or y + half > geometry["height"]
    ):
        return True
    return any(
        x - half < r["x"] + r["width"]
        and x + half > r["x"]
        and y - half < r["y"] + r["height"]
        and y + half > r["y"]
        for r in [*geometry["walls"], *doors]
    )


def move(x, y, dx, dy, seconds, geometry=None, doors=()):
    geometry = geometry or MAP
    length = math.hypot(dx, dy)
    if not length:
        return x, y
    # Substeps prevent tunnelling even after a delayed tick.
    steps = max(1, math.ceil(seconds / 0.02))
    distance = geometry["speed"] * seconds / steps / max(1, length)
    for _ in range(steps):
        nx = x + dx * distance
        if not blocked(nx, y, geometry, doors):
            x = nx
        ny = y + dy * distance
        if not blocked(x, ny, geometry, doors):
            y = ny
    return x, y
