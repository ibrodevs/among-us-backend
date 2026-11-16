import secrets

from django.db import transaction

from rooms.models import Room, RoomMembership
from rooms.signals import lobby_changed

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_room_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def create_room_for_player(player, *, max_players: int) -> Room:
    for _ in range(20):
        with transaction.atomic():
            room, created = Room.objects.get_or_create(
                code=new_room_code(),
                defaults={"host": player, "max_players": max_players},
            )
            if created:
                RoomMembership.objects.create(room=room, player=player)
                return room
    raise RuntimeError("Could not allocate a unique room code")


def notify_lobby_changed(room_code: str) -> None:
    transaction.on_commit(
        lambda: lobby_changed.send_robust(sender=Room, room_code=room_code)
    )
