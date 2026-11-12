import secrets
from django.db import IntegrityError, transaction
from rooms.models import Room, RoomMembership

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_room_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def create_room_for_player(player, *, max_players: int) -> Room:
    for _ in range(20):
        try:
            with transaction.atomic():
                room = Room.objects.create(code=new_room_code(), host=player, max_players=max_players)
                RoomMembership.objects.create(room=room, player=player)
                return room
        except IntegrityError:
            continue
    raise RuntimeError("Could not allocate a unique room code")
