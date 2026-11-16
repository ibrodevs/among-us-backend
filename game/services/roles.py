import secrets

from game.models import PlayerGameState

from game.physics import MAP

SPAWN_POINTS = tuple((p["x"], p["y"]) for p in MAP["spawns"])


def assign_roles(player_ids):
    if not 4 <= len(player_ids) <= 10:
        raise ValueError("A match requires 4 to 10 players")
    count = 1 if len(player_ids) <= 6 else 2
    impostors = set(secrets.SystemRandom().sample(player_ids, count))
    return {
        player_id: (
            PlayerGameState.Role.IMPOSTOR
            if player_id in impostors
            else PlayerGameState.Role.CREW
        )
        for player_id in player_ids
    }
