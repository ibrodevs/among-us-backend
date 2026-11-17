"""Immutable versioned maps. Never change the interpretation of saved v1 games."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def get_map(version=1):
    if version not in [1, 2]:
        raise ValueError("Unsupported map version")
    return json.loads(
        (
            Path(__file__).parent / ("asterion.json" if version == 2 else "v1.json")
        ).read_text()
    )


def game_map(game):
    return get_map(game.map_version)


def task_stations(game):
    return {t["point"]: t for t in game_map(game)["tasks"]}


def active_rooms(game):
    return {
        r["id"]
        for r in game_map(game).get("rooms", [])
        if game.map_mode == "full" or r["compact"]
    }


def closed_doors(game, now=None):
    from django.utils import timezone

    now = now or timezone.now()
    if game.map_version == 1:
        return []
    ctx = getattr(game, "_frame", None)
    ids = (
        {d.door_id for d in ctx["doors"] if d.closed_until > now}
        if ctx is not None
        else set(
            game.doors.filter(closed_until__gt=now).values_list("door_id", flat=True)
        )
    )
    return [
        d["bounds"]
        for d in game_map(game)["doors"]
        if d["id"] in ids or (game.map_mode == "compact" and not d["compact"])
    ]
