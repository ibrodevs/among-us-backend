"""Room bounds and host-selected role requirements."""

MIN_PLAYERS = 4
MAX_PLAYERS = 20
PLAYER_COLORS = 20
ROLE_MINIMUMS = {1: 4, 2: 7, 3: 10}


def minimum_players(count):
    if type(count) is not int or count not in ROLE_MINIMUMS:
        raise ValueError("Количество предателей должно быть от 1 до 3")
    return ROLE_MINIMUMS[count]
