from django.db import transaction
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from game.models import GameSession, PlayerGameState
from game.services.events import publish_start
from game.services.roles import SPAWN_POINTS, assign_roles
from rooms.models import Room, RoomMembership
from rooms.serializers import RoomSerializer


class StartConflict(APIException):
    status_code = 409
    default_detail = "Room already started"


@transaction.atomic
def start_game(*, code, player):
    try:
        room = Room.objects.select_for_update().get(code=code.upper())
    except Room.DoesNotExist:
        raise NotFound("Room does not exist") from None

    # join_room and leave_room take this same Room lock. The roster cannot
    # change between this read and commit through the existing room API.
    members = list(RoomMembership.objects.select_for_update().filter(room=room).order_by("joined_at", "pk"))
    player_ids = [member.player_id for member in members]
    if player.pk not in player_ids or room.host_id != player.pk:
        raise PermissionDenied("Only the room host can start the game")
    if room.status != Room.Status.WAITING or GameSession.objects.filter(room=room).exists():
        raise StartConflict()
    if len(members) < 4:
        raise StartConflict("At least 4 players required")
    if len(members) > min(room.max_players, 10):
        raise StartConflict("Too many players in room")

    roles = assign_roles(player_ids)
    game = GameSession.objects.create(room=room)
    PlayerGameState.objects.bulk_create([
        PlayerGameState(game=game, player_id=player_id, role=roles[player_id], x=point[0], y=point[1])
        for player_id, point in zip(player_ids, SPAWN_POINTS)
    ])
    room.status = Room.Status.PLAYING
    room.save(update_fields=["status"])
    room_data = RoomSerializer(room).data
    transaction.on_commit(lambda: publish_start(room_data, player_ids))
    return room_data
