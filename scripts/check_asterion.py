"""Validate actual collision reachability in both configurations, not just JSON counts."""

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
            (r["id"], r["bounds"]["x"] + 450, r["bounds"]["y"] + 260)
            for r in m["rooms"]
            if r["id"] in active
        ]
        + [(t["point"], t["x"], t["y"]) for t in m["tasks"] if t["room_id"] in active]
        + [
            (p["id"], p["x"], p["y"])
            for p in m["sabotage_panels"]
            if p["room_id"] in active
        ]
    )
    for name, x, y in goals:
        assert (round(x / step), round(y / step)) in visited, (mode, name, x, y)
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
