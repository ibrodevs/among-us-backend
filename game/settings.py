from game.limits import MIN_PLAYERS, MAX_PLAYERS, minimum_players
from rest_framework.exceptions import ValidationError

DEFAULTS = dict(
    map_version=2,
    max_players=MAX_PLAYERS,
    impostor_count=2,
    area="auto",
    speed=220,
    discussion_seconds=30,
    voting_seconds=45,
    kill_cooldown=25,
    critical_seconds=90,
    common_tasks=1,
    short_tasks=4,
    long_tasks=2,
    anonymous_votes=True,
    confirm_ejects=False,
    special_roles=False,
    critical_sabotages=True,
    vents=True,
    ghost_tasks=True,
    ghost_sabotage=False,
    crew_vision=520,
    impostor_vision=700,
    self_vote=True,
)
RANGES = {
    "map_version": (1, 2),
    "max_players": (MIN_PLAYERS, MAX_PLAYERS),
    "impostor_count": (1, 3),
    "speed": (200, 230),
    "discussion_seconds": (5, 120),
    "voting_seconds": (5, 120),
    "kill_cooldown": (10, 60),
    "critical_seconds": (45, 120),
    "common_tasks": (0, 2),
    "short_tasks": (1, 7),
    "long_tasks": (0, 3),
    "crew_vision": (250, 800),
    "impostor_vision": (350, 1000),
}


def settings_for(room):
    return {**DEFAULTS, **room.settings, "max_players": room.max_players}


def validate_settings(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValidationError({"detail": "Unknown game settings"})
    result = {**DEFAULTS, **data}
    for key, value in result.items():
        if key in RANGES:
            low, high = RANGES[key]
            if type(value) is not int or not low <= value <= high:
                raise ValidationError({"detail": f"{key}: expected {low}–{high}"})
        elif key == "area":
            if value not in ["auto", "compact", "full"]:
                raise ValidationError({"detail": "Invalid area"})
        elif type(value) is not bool:
            raise ValidationError({"detail": f"{key}: expected boolean"})
    if (
        not 4
        <= sum(result[k] for k in ["common_tasks", "short_tasks", "long_tasks"])
        <= 9
    ):
        raise ValidationError({"detail": "Choose 4–9 tasks"})
    if result["max_players"] < minimum_players(result["impostor_count"]):
        raise ValidationError(
            {
                "detail": f"Для {result['impostor_count']} предателей требуется минимум {minimum_players(result['impostor_count'])} игроков"
            }
        )
    return result
