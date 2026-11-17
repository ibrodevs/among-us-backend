"""Deterministic original Asterion layout, not a scaled v1 map."""

import json
import math
from collections import deque
from pathlib import Path
from scripts.asterion_rooms import apply_room_definitions

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
    decor = apply_room_definitions(rooms, rect)
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
    for room in rooms:
        outline = []
        for x0, y0, x1, y1 in room["outline"]:
            horizontal = y0 == y1
            cuts = {x0, x1} if horizontal else {y0, y1}
            for corridor in corridors:
                b = corridor["bounds"]
                cuts.update(
                    [b["x"], b["x"] + b["width"]]
                    if horizontal
                    else [b["y"], b["y"] + b["height"]]
                )
            cuts = (
                sorted(v for v in cuts if min(x0, x1) <= v <= max(x0, x1))
                if horizontal
                else sorted(v for v in cuts if min(y0, y1) <= v <= max(y0, y1))
            )
            for low, high in zip(cuts, cuts[1:]):
                mx, my = (
                    ((low + high) / 2, y0) if horizontal else (x0, (low + high) / 2)
                )
                if not any(contains(c["bounds"], mx, my) for c in corridors):
                    outline.append(
                        [low, y0, high, y1] if horizontal else [x0, low, x1, high]
                    )
        room["outline"] = outline
    floor = [p for r in rooms for p in r["floor_parts"]] + [
        c["bounds"] for c in corridors
    ]
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
    walls.extend(d["bounds"] for d in decor if d["solid"])
    tasks = []
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

    # Resolve authored interaction approaches onto a clear floor cell. The same
    # coordinate is used by art, server validation, minimap and exit placement.
    def clear_point(room_id, target, used):
        room = next(r for r in rooms if r["id"] == room_id)
        b = room["bounds"]
        candidates = []
        for x in range(math.ceil(b["x"] / 40) * 40, b["x"] + b["width"], 40):
            for y in range(math.ceil(b["y"] / 40) * 40, b["y"] + b["height"], 40):
                if not any(contains(p, x, y) for p in room["floor_parts"]):
                    continue
                if any(
                    x - 38 < p["x"] + p["width"]
                    and x + 38 > p["x"]
                    and y - 38 < p["y"] + p["height"]
                    and y + 38 > p["y"]
                    for p in walls
                ):
                    continue
                if any(math.hypot(x - q["x"], y - q["y"]) < 100 for q in used):
                    continue
                candidates.append(dict(x=x, y=y))
        assert candidates, room_id
        return min(
            candidates,
            key=lambda p: math.hypot(p["x"] - target["x"], p["y"] - target["y"]),
        )

    used = []
    for i, point in enumerate([*tasks, *vents]):
        target = dict(x=point["x"], y=point["y"] + (i % 3 - 1) * 45)
        point.update(clear_point(point["room_id"], target, used))
        used.append(point)
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
    center = dict(x=2930, y=2040)
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
    for panel in panels:
        panel.update(clear_point(panel["room_id"], panel, []))
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
    node_positions = {
        r["id"]: clear_point(
            r["id"], dict(x=r["bounds"]["x"] + 450, y=r["bounds"]["y"] + 260), []
        )
        for r in rooms
    }
    spawn_points = []
    for i in range(10):
        angle = i * math.pi / 5
        spawn_points.append(
            clear_point(
                "nexus",
                dict(x=2930 + 175 * math.cos(angle), y=1970 + 150 * math.sin(angle)),
                spawn_points,
            )
        )
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

        start = (node_positions[a["id"]]["x"] // 20, node_positions[a["id"]]["y"] // 20)
        goal = (node_positions[b["id"]]["x"] // 20, node_positions[b["id"]]["y"] // 20)
        queue = deque([start])
        previous = {start: None}
        while queue and goal not in previous:
            x, y = queue.popleft()
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                cell = (x + dx, y + dy)
                if cell not in previous and free(cell):
                    previous[cell] = (x, y)
                    queue.append(cell)
        assert goal in previous, (
            corridor["id"],
            free(start),
            free(goal),
            len(previous),
            start,
            goal,
        )
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
        design_revision="2.1",
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
        spawns=spawn_points,
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
            nodes=[dict(id=r["id"], **node_positions[r["id"]]) for r in rooms],
            edges=edges,
            routes=routes,
        ),
        occlusion=[*walls],
        audio_zones=[
            dict(
                room_id=r["id"],
                profile=r["visual"]["audioProfile"],
                surface="metal" if r["sector"] != "science" else "soft",
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
