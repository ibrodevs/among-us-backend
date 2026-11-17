"""Validate actual collision reachability in both configurations, not just JSON counts."""

import math
from collections import deque
from game.maps import get_map
from game.physics import blocked


def validate(mode):
    m = get_map(2)
    active = {r["id"] for r in m["rooms"] if mode == "full" or r["compact"]}
    doors = [d["bounds"] for d in m["doors"] if mode == "compact" and not d["compact"]]
    step = 40
    origin = (round(m["spawns"][0]["x"] / step), round(m["spawns"][0]["y"] / step))
    visited = {origin}
    queue = deque([origin])
    while queue:
        x, y = queue.popleft()
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            q = (x + dx, y + dy)
            if (
                q not in visited
                and 0 < q[0] * step < m["width"]
                and 0 < q[1] * step < m["height"]
                and not blocked(q[0] * step, q[1] * step, m, doors)
            ):
                visited.add(q)
                queue.append(q)
    goals = (
        [
            (
                r["id"],
                next(n["x"] for n in m["navigation"]["nodes"] if n["id"] == r["id"]),
                next(n["y"] for n in m["navigation"]["nodes"] if n["id"] == r["id"]),
            )
            for r in m["rooms"]
            if r["id"] in active
        ]
        + [(v["id"], v["x"], v["y"]) for v in m["vents"] if v["room_id"] in active]
        + [(v["id"], v["x"], v["y"]) for v in m["terminals"] if v["room_id"] in active]
        + [("spawn", v["x"], v["y"]) for v in m["spawns"]]
        + [(t["point"], t["x"], t["y"]) for t in m["tasks"] if t["room_id"] in active]
        + [
            (p["id"], p["x"], p["y"])
            for p in m["sabotage_panels"]
            if p["room_id"] in active
        ]
    )
    for name, x, y in goals:
        assert not blocked(x, y, m, doors), ("blocked interaction", mode, name, x, y)
        assert any(
            (qx * step - x) ** 2 + (qy * step - y) ** 2 < 40**2 for qx, qy in visited
        ), (mode, name, x, y)
    for route in m["navigation"]["routes"]:
        for a, b in zip(route["waypoints"], route["waypoints"][1:]):
            count = max(1, math.ceil(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) / 10))
            for i in range(count + 1):
                assert not blocked(
                    a["x"] + (b["x"] - a["x"]) * i / count,
                    a["y"] + (b["y"] - a["y"]) * i / count,
                    m,
                ), ("navigation segment intersects collider", route["door_id"])
    for v in m["vents"]:
        for link in v["connected_vent_ids"]:
            target = next(t for t in m["vents"] if t["id"] == link)
            assert v["id"] in target["connected_vent_ids"]
            assert target["network"] == v["network"]
    return {
        "mode": mode,
        "reachable_cells": len(visited),
        "verified_goals": len(goals),
        "rooms": len(active),
    }


if __name__ == "__main__":
    for mode in ["full", "compact"]:
        print(validate(mode))
