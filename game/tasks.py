"""Task-specific challenges and validators, shared metadata, no client-selected assignment."""

import json
import secrets
from pathlib import Path

RNG = secrets.SystemRandom()
NAMES = [
    "Connect Wires",
    "Power Routing",
    "Data Transfer",
    "Engine Calibration",
    "Oxygen Filters",
    "Fuel Distribution",
    "Shield Alignment",
    "Medical Scan",
    "Sample Analysis",
    "Cargo Sorting",
    "Antenna Alignment",
    "Signal Frequency",
    "Navigation Route",
    "Asteroid Defense",
    "Debris Removal",
    "Thermal Balance",
    "Coolant Valves",
    "Access Terminal",
    "Memory Matrix",
    "Pressure Control",
]
KINDS = [
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
LONG = {"upload", "medical_scan", "sample_analysis", "thermal_balance"}
CATALOG = {
    kind: dict(
        id=kind,
        title=title,
        category="common" if kind == "wires" else ("long" if kind in LONG else "short"),
        seconds=8 if kind in LONG else 3,
        stages=2 if kind in {"upload", "sample_analysis"} else 1,
    )
    for kind, title in zip(KINDS, NAMES)
}


def challenge(kind):
    if kind == "wires":
        return RNG.sample(range(4), 4)
    if kind == "power_routing":
        return [bit for _ in range(3) for bit in RNG.sample([0, 1], 2)]
    if kind in {"upload", "medical_scan"}:
        return [secrets.randbelow(100000)]
    if kind == "engine_calibration":
        return [RNG.randrange(20, 81, 5), RNG.randrange(20, 81, 5)]
    if kind == "oxygen_filters":
        return RNG.sample(range(3), 3)
    if kind == "fuel_distribution":
        a = RNG.randrange(20, 51, 5)
        b = RNG.randrange(15, 81 - a, 5)
        return [a, b, 100 - a - b]
    if kind == "shield_alignment":
        return [RNG.randrange(4) for _ in range(4)]
    if kind == "sample_analysis":
        index = RNG.randrange(5)
        return [index, *[85 if i == index else 25 for i in range(5)]]
    if kind == "cargo_sorting":
        return [RNG.randrange(3) for _ in range(6)]
    if kind == "antenna_alignment":
        return [RNG.randrange(0, 360, 10), RNG.randrange(10, 81, 5)]
    if kind == "signal_frequency":
        return [RNG.randrange(10, 91), RNG.randrange(0, 361, 15)]
    if kind == "navigation_route":
        return RNG.sample(range(9), 5)
    if kind in {"asteroid_defense", "debris_removal"}:
        return list(range(7 if kind == "asteroid_defense" else 6))
    if kind == "thermal_balance":
        a = RNG.randrange(30, 66, 5)
        b = RNG.randrange(35, 66, 5)
        return [a, b, 150 - a - b]
    if kind == "coolant_valves":
        return RNG.sample(range(4), 4)
    if kind == "access_terminal":
        return [RNG.randrange(10) for _ in range(6)]
    if kind == "sequence":
        return [RNG.randrange(4) for _ in range(6)]
    if kind == "pressure_control":
        return [50, 50, 50]
    raise ValueError("Unknown task type")


def valid_solution(kind, seed, solution):
    if (
        not isinstance(solution, list)
        or len(solution) > 32
        or any(type(v) is not int for v in solution)
    ):
        return False
    if kind == "medical_scan":
        return solution == [seed[0], 3]
    if kind == "upload":
        return solution == [seed[0]]
    if kind == "sample_analysis":
        return solution == [seed[0]]
    if kind == "oxygen_filters":
        return solution == [3, 3, 3, *seed]
    if kind in {"asteroid_defense", "debris_removal"}:
        return len(solution) == len(seed) and sorted(solution) == seed
    if kind == "coolant_valves":
        return solution == [v for n in seed for v in [n, n, n]]
    return solution == seed


def assign_tasks(game, player_ids):
    from game.maps import game_map, active_rooms
    from game.models import TaskAssignment

    data = game_map(game)
    active = active_rooms(game)
    available = [t for t in data["tasks"] if t["room_id"] in active]
    common = [t for t in available if t["type"] == "wires"][
        : game.settings["common_tasks"]
    ]
    for pid in player_ids:
        selected = list(common)
        used = {t["point"] for t in selected}
        for category, count in [
            ("short", game.settings["short_tasks"]),
            ("long", game.settings["long_tasks"]),
        ]:
            pool = [t for t in available if CATALOG[t["type"]]["category"] == category]
            RNG.shuffle(pool)
            for _ in range(count):
                candidates = [
                    t
                    for t in pool
                    if t["point"] not in used
                    and t["room_id"] not in {v["room_id"] for v in selected}
                ]
                if not candidates:
                    candidates = [t for t in pool if t["point"] not in used]
                t = candidates[0]
                selected.append(t)
                used.add(t["point"])
        for t in selected:
            definition = CATALOG[t["type"]]
            destination = next(
                (
                    q
                    for q in available
                    if q["room_id"] != t["room_id"] and q["point"] not in used
                ),
                t,
            )
            TaskAssignment.objects.create(
                game=game,
                player_id=pid,
                task_type=t["type"],
                task_point=t["point"],
                stage_total=definition["stages"],
                extra={"destination": destination["point"]},
            )


if __name__ == "__main__":
    target = (
        Path(__file__).resolve().parents[2]
        / "among-us-frontend/src/features/game/engine/task-catalog.json"
    )
    target.write_text(json.dumps(CATALOG, ensure_ascii=False, indent=2) + "\n")
