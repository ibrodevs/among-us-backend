"""Collision-aware walking distances, at configured 220 units/s, with open doors."""

import json
import math
from collections import deque
from game.maps import get_map
from game.physics import blocked


def measure(mode):
    m = get_map(2)
    step = 40
    gates = [d["bounds"] for d in m["doors"] if mode == "compact" and not d["compact"]]
    active = {r["id"] for r in m["rooms"] if mode == "full" or r["compact"]}
    free = {
        (x, y)
        for x in range(1, m["width"] // step)
        for y in range(1, m["height"] // step)
        if not blocked(x * step, y * step, m, gates)
    }

    def nearest(p):
        return min(
            free,
            key=lambda q: (q[0] * step - p["x"]) ** 2 + (q[1] * step - p["y"]) ** 2,
        )

    def distances(p):
        start = nearest(p)
        d = {start: 0}
        todo = deque([start])
        while todo:
            x, y = todo.popleft()
            for q in [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]:
                if q in free and q not in d:
                    d[q] = d[x, y] + step
                    todo.append(q)
        return d

    origin = distances(m["spawns"][0])
    panels = {
        p["id"]: round(origin[nearest(p)] / 220, 2)
        for p in m["sabotage_panels"]
        if p["room_id"] in active
    }
    tasks = [t for t in m["tasks"] if t["room_id"] in active]
    max_task = 0
    for node in m["navigation"]["nodes"]:
        if node["id"] not in active:
            continue
        d = distances(node)
        max_task = max(max_task, max(d[nearest(t)] for t in tasks))
    sector_for = {r["id"]: r["sector"] for r in m["rooms"]}
    crossings = [
        dict(rooms=r["rooms"], seconds=round(r["distance"] / 220, 2))
        for r in m["navigation"]["routes"]
        if (mode == "full" or r["compact"])
        and sector_for[r["rooms"][0]] != sector_for[r["rooms"][1]]
    ]
    return dict(
        mode=mode,
        speed=220,
        method="40-unit collision grid, Manhattan shortest paths; no player/input/network delay; open dynamic doors",
        nexus_to_critical_seconds=panels,
        max_room_anchor_to_task_seconds=round(max_task / 220, 2),
        adjacent_sector_routes=crossings,
        reachable_terminals=len(tasks),
        rooms=len(active),
    )


if __name__ == "__main__":
    print(
        json.dumps(
            [measure(mode) for mode in ["compact", "full"]],
            ensure_ascii=False,
            indent=2,
        )
    )
