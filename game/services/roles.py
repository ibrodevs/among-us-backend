import secrets

from game.models import PlayerGameState

from game.physics import MAP, blocked
from game.limits import MAX_PLAYERS, MIN_PLAYERS, minimum_players


def legacy_spawns():
    # Keep the original ten slots and immutable v1 JSON. Extra slots use the
    # same actual collider map, with at least 40 units between hitboxes.
    points = [(p["x"], p["y"]) for p in MAP["spawns"]]
    candidates = sorted(
        ((605 + 44 * x, 450 + 44 * y) for x in range(-10, 21) for y in range(-7, 8)),
        key=lambda p: (p[0] - 800) ** 2 + (p[1] - 450) ** 2,
    )
    for x, y in candidates:
        if len(points) >= MAX_PLAYERS:
            break
        if not blocked(x, y, MAP) and all(
            (x - a) ** 2 + (y - b) ** 2 >= 40**2 for a, b in points
        ):
            points.append((x, y))
    if len(points) != MAX_PLAYERS:
        raise ValueError("Not enough safe legacy spawn slots")
    return tuple(points)


SPAWN_POINTS = legacy_spawns()


def spawn_points(game):
    if game.map_version == 1:
        return [dict(x=x, y=y) for x, y in SPAWN_POINTS]
    from game.maps import game_map

    return game_map(game)["spawns"]


def assign_roles(player_ids, impostor_count=2):
    count = impostor_count
    required = minimum_players(count)
    if not MIN_PLAYERS <= len(player_ids) <= MAX_PLAYERS or len(player_ids) < required:
        raise ValueError(f"Для {count} предателей требуется минимум {required} игроков")
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("Duplicate player identities")
    impostors = set(secrets.SystemRandom().sample(player_ids, count))
    return {
        player_id: (
            PlayerGameState.Role.IMPOSTOR
            if player_id in impostors
            else PlayerGameState.Role.CREW
        )
        for player_id in player_ids
    }
