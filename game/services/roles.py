import secrets

from game.models import PlayerGameState

# Central spawn area of the logical 1600 x 900 map, away from its boundaries.
# Stage B must keep this area clear when introducing collision geometry.
SPAWN_POINTS = (
    (720, 400), (760, 400), (800, 400), (840, 400), (880, 400),
    (720, 450), (760, 450), (800, 450), (840, 450), (880, 450),
)


def assign_roles(player_ids):
    if not 4 <= len(player_ids) <= 10:
        raise ValueError("A match requires 4 to 10 players")
    count = 1 if len(player_ids) <= 6 else 2
    impostors = set(secrets.SystemRandom().sample(player_ids, count))
    return {
        player_id: PlayerGameState.Role.IMPOSTOR if player_id in impostors else PlayerGameState.Role.CREW
        for player_id in player_ids
    }
