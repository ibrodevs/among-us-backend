"""Immutable versioned maps. Never change the interpretation of saved v1 games."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def get_map(version=1):
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
    ids = {d["door_id"] for d in game.doors.filter(closed_until__gt=now)}
    return [
        d["bounds"]
        for d in game_map(game)["doors"]
        if d["id"] in ids or (game.map_mode == "compact" and not d["compact"])
    ]
