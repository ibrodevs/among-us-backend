"""Deterministic original Asterion layout, not a scaled v1 map."""

import json
import math
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "engineering": [
        ("reactor", "Реактор", 0, 1),
        ("power", "Электростанция", 1, 1),
        ("engines", "Двигатели", 0, 2),
        ("cooling", "Охлаждение", 1, 2),
        ("maintenance", "Мастерская", 0, 3),
    ],
    "command": [
        ("bridge", "Мостик", 1, 0),
        ("navigation", "Навигация", 2, 0),
        ("comms", "Связь", 3, 0),
        ("security", "Безопасность", 2, 1),
        ("observatory", "Обсерватория", 3, 1),
    ],
    "science": [
        ("medical", "Медблок", 1, 3),
        ("laboratory", "Лаборатория", 1, 4),
        ("biodome", "Биокупол", 2, 3),
        ("oxygen", "Кислородная", 2, 4),
        ("quarters", "Жилой блок", 3, 4),
    ],
    "logistics": [
        ("cargo", "Грузовой отсек", 3, 2),
        ("storage", "Склад", 4, 1),
        ("data", "Центр данных", 4, 2),
        ("transit", "Транспортный узел", 3, 3),
        ("airlock", "Космический шлюз", 4, 3),
    ],
}
TYPES = [
    "wires",
    "power_routing",
    "upload",
    "engine_calibration",
    "oxygen_filters",
    "fuel_distribution",
    "shield_alignment",
    "medical_scan",
    "sample_analysis",
    "cargo_sorting",
    "antenna_alignment",
    "signal_frequency",
    "navigation_route",
    "asteroid_defense",
    "debris_removal",
    "thermal_balance",
    "coolant_valves",
    "access_terminal",
    "sequence",
    "pressure_control",
]


def rect(x, y, w, h):
    return dict(x=x, y=y, width=w, height=h)


def contains(r, x, y):
    return r["x"] <= x <= r["x"] + r["width"] and r["y"] <= y <= r["y"] + r["height"]


def build():
    rooms = []
    for sector, entries in GROUPS.items():
        for rid, name, col, row in entries:
            rooms.append(
                dict(
                    id=rid,
                    name=name,
                    sector=sector,
                    col=col,
                    row=row,
                    compact=1 <= col <= 3 and 1 <= row <= 3,
                    bounds=rect(200 + col * 1140, 230 + row * 740, 900, 520),
                )
            )
    rooms.append(
        dict(
            id="nexus",
            name="Nexus Hall",
            sector="nexus",
            col=2,
            row=2,
            compact=True,
            bounds=rect(2480, 1710, 900, 520),
        )
    )
    grid = {(r["col"], r["row"]): r for r in rooms}
    corridors = []
    doors = []
    edges = []
    for (col, row), a in grid.items():
        for dc, dr in [(1, 0), (0, 1)]:
            b = grid.get((col + dc, row + dr))
            if not b:
                continue
            ar, br = a["bounds"], b["bounds"]
            cx = ar["x"] + 450
            cy = ar["y"] + 260
            bounds = (
                rect(ar["x"] + 880, cy - 90, 280, 180)
                if dc
                else rect(cx - 90, ar["y"] + 500, 180, 260)
            )
            did = a["id"] + "--" + b["id"]
            corridors.append(dict(id=did, bounds=bounds, rooms=[a["id"], b["id"]]))
            door = (
                rect(ar["x"] + 1008, cy - 90, 24, 180)
                if dc
                else rect(cx - 90, ar["y"] + 618, 180, 24)
            )
            doors.append(
                dict(
                    id=did,
                    group=a["sector"],
                    bounds=door,
                    rooms=[a["id"], b["id"]],
                    compact=a["compact"] and b["compact"],
                )
            )
            edges.append([a["id"], b["id"]])
    floor = [r["bounds"] for r in rooms] + [c["bounds"] for c in corridors]
    xs = sorted({0, 6144, *[v for r in floor for v in [r["x"], r["x"] + r["width"]]]})
    ys = sorted({0, 4096, *[v for r in floor for v in [r["y"], r["y"] + r["height"]]]})
    walls = []
    previous = {}
    for y0, y1 in zip(ys, ys[1:]):
        spans = []
        start = None
        for x0, x1 in zip(xs, xs[1:]):
            solid = not any(contains(r, (x0 + x1) / 2, (y0 + y1) / 2) for r in floor)
            if solid and start is None:
                start = x0
            if not solid and start is not None:
                spans.append((start, x0))
                start = None
        if start is not None:
            spans.append((start, xs[-1]))
        current = {}
        for x0, x1 in spans:
            old = previous.get((x0, x1))
            if old is not None:
                walls[old]["height"] += y1 - y0
                current[(x0, x1)] = old
            else:
                current[(x0, x1)] = len(walls)
                walls.append(rect(x0, y0, x1 - x0, y1 - y0))
        previous = current
    tasks = []
    decor = []
    vents = []
    for i, r in enumerate(rooms[:-1]):
        b = r["bounds"]
        cx = b["x"] + 450
        cy = b["y"] + 260
        for j in range(2):
            kind = [
                "shield_alignment",
                "power_routing",
                "engine_calibration",
                "coolant_valves",
                "wires",
                "access_terminal",
                "navigation_route",
                "signal_frequency",
                "sequence",
                "antenna_alignment",
                "medical_scan",
                "sample_analysis",
                "oxygen_filters",
                "pressure_control",
                "debris_removal",
                "cargo_sorting",
                "fuel_distribution",
                "upload",
                "thermal_balance",
                "asteroid_defense",
            ][i]
            if j == 1 and r["id"] in ["power", "security"]:
                kind = "wires"
            tasks.append(
                dict(
                    point=r["id"] + "-" + str(j),
                    type=kind,
                    room_id=r["id"],
                    x=cx + (-240 if j == 0 else 240),
                    y=cy + 60,
                    seconds=(
                        8
                        if kind in ["upload", "medical_scan", "sample_analysis"]
                        else 3
                    ),
                )
            )
        for j in range(3):
            q = rect(b["x"] + 140 + j * 240, b["y"] + 75, 130, 90)
            walls.append(q)
            decor.append(
                dict(
                    id=r["id"] + "-machine" + str(j),
                    kind=[
                        "reactor",
                        "console",
                        "engine",
                        "pipes",
                        "console",
                        "console",
                        "console",
                        "antenna",
                        "console",
                        "telescope",
                        "capsule",
                        "capsule",
                        "pod",
                        "pipes",
                        "bed",
                        "crate",
                        "fuel",
                        "servers",
                        "tram",
                        "airlock",
                    ][i],
                    room_id=r["id"],
                    bounds=q,
                )
            )
        vents.append(
            dict(
                id="vent-" + r["id"],
                room_id=r["id"],
                network=(
                    0
                    if r["sector"] == "engineering"
                    else (1 if r["sector"] == "command" else 2)
                ),
                x=cx,
                y=cy + 155,
                connected_vent_ids=[],
            )
        )
    for network in range(3):
        nodes = [v for v in vents if v["network"] == network]
        for i, v in enumerate(nodes):
            v["connected_vent_ids"] = [
                nodes[(i - 1) % len(nodes)]["id"],
                nodes[(i + 1) % len(nodes)]["id"],
            ]
    for network in range(3):
        active = [
            v
            for v in vents
            if v["network"] == network
            and next(r for r in rooms if r["id"] == v["room_id"])["compact"]
        ]
        if len(active) > 1:
            for i, v in enumerate(active):
                v["connected_vent_ids"] = sorted(
                    set(
                        v["connected_vent_ids"]
                        + [
                            active[(i - 1) % len(active)]["id"],
                            active[(i + 1) % len(active)]["id"],
                        ]
                    )
                )
    center = dict(x=2930, y=1970)
    panels = []
    for kind, rs in {
        "reactor": ["power", "transit"],
        "oxygen": ["medical", "observatory"],
        "lights": ["power"],
        "comms": ["observatory"],
    }.items():
        for i, rid in enumerate(rs):
            r = next(r for r in rooms if r["id"] == rid)
            b = r["bounds"]
            panels.append(
                dict(
                    id=kind + "-" + str(i),
                    type=kind,
                    room_id=rid,
                    x=b["x"] + 450,
                    y=b["y"] + 230,
                )
            )
    cameras = [
        dict(
            id="cam-" + r["id"],
            room_id=r["id"],
            x=r["bounds"]["x"] + 450,
            y=r["bounds"]["y"] + 260,
            radius=550,
        )
        for r in rooms
        if r["compact"] and r["id"] != "nexus"
    ]
    routes = []
    by_id = {r["id"]: r for r in rooms}
    for corridor in corridors:
        a, b = [by_id[key] for key in corridor["rooms"]]
        region = [a["bounds"], b["bounds"], corridor["bounds"]]

        def free(cell):
            x, y = cell[0] * 20 + 10, cell[1] * 20 + 10
            return any(contains(r, x, y) for r in region) and not any(
                x - 14 < r["x"] + r["width"]
                and x + 14 > r["x"]
                and y - 14 < r["y"] + r["height"]
                and y + 14 > r["y"]
                for r in walls
            )

        start = ((a["bounds"]["x"] + 440) // 20, (a["bounds"]["y"] + 250) // 20)
        goal = ((b["bounds"]["x"] + 440) // 20, (b["bounds"]["y"] + 250) // 20)
        queue = deque([start])
        previous = {start: None}
        while queue and goal not in previous:
            x, y = queue.popleft()
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                cell = (x + dx, y + dy)
                if cell not in previous and free(cell):
                    previous[cell] = (x, y)
                    queue.append(cell)
        assert goal in previous, corridor["id"]
        path = []
        cell = goal
        while cell is not None:
            path.append(cell)
            cell = previous[cell]
        path.reverse()
        turns = [
            q
            for j, q in enumerate(path)
            if j in [0, len(path) - 1]
            or (q[0] - path[j - 1][0], q[1] - path[j - 1][1])
            != (path[j + 1][0] - q[0], path[j + 1][1] - q[1])
        ]
        points = [dict(x=x * 20 + 10, y=y * 20 + 10) for x, y in turns]
        routes.append(
            dict(
                rooms=corridor["rooms"],
                door_id=corridor["id"],
                compact=a["compact"] and b["compact"],
                waypoints=points,
                distance=sum(
                    math.hypot(q["x"] - p["x"], q["y"] - p["y"])
                    for p, q in zip(points, points[1:])
                ),
            )
        )
    return dict(
        map_id="asterion",
        version=2,
        map_version=2,
        width=6144,
        height=4096,
        player_hitbox=28,
        speed=220,
        rooms=rooms,
        zones=rooms,
        corridors=corridors,
        walls=walls,
        doors=doors,
        spawns=[dict(x=2780 + i * 34, y=1970) for i in range(10)],
        emergency=center,
        emergency_stations=[dict(id="nexus-emergency", **center)],
        tasks=tasks,
        vents=vents,
        sabotage_panels=panels,
        cameras=cameras,
        terminals=[
            dict(id="security", room_id="security", type="cameras", x=2930, y=1230),
            dict(id="admin", room_id="nexus", type="admin", x=3080, y=1970),
            dict(id="vitals", room_id="medical", type="vitals", x=1790, y=2710),
        ],
        decorations=decor,
        navigation=dict(
            nodes=[
                dict(id=r["id"], x=r["bounds"]["x"] + 450, y=r["bounds"]["y"] + 260)
                for r in rooms
            ],
            edges=edges,
            routes=routes,
        ),
        occlusion=[*walls],
        audio_zones=[
            dict(
                room_id=r["id"], surface="metal" if r["sector"] != "science" else "soft"
            )
            for r in rooms
        ],
    )


if __name__ == "__main__":
    data = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    for p in [
        ROOT / "game/maps/asterion.json",
        ROOT.parent / "among-us-frontend/src/features/game/engine/asterion.json",
    ]:
        p.write_text(data)
    print("Asterion: 21 rooms, 40 task stations, 20 vents, version 2")
