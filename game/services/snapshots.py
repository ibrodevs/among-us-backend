from rest_framework.exceptions import AuthenticationFailed

from game.models import PlayerGameState
from rooms.models import Room, RoomMembership
from rooms.serializers import RoomSerializer


def get_member_room(code, player_id):
    try:
        room = Room.objects.get(code=code)
    except Room.DoesNotExist:
        raise AuthenticationFailed("Invalid guest or room") from None
    if not RoomMembership.objects.filter(room=room, player_id=player_id).exists():
        raise AuthenticationFailed("Invalid guest or room")
    return room


def own_start_data(room, player_id):
    """Explicit allowlist: never serialize a whole game or another player's tasks."""
    state = PlayerGameState.objects.select_related("game").filter(game__room=room, player_id=player_id).first()
    if state is None:
        return None
    tasks = state.game.tasks.filter(player_id=player_id).order_by("id")
    return {
        "type": "game.started",
        "game_id": str(state.game_id),
        "room_code": room.code,
        "started_at": state.game.started_at.isoformat(),
        "state_version": state.game.state_version,
        "role": state.role,
        "tasks": [{
            "id": str(task.pk),
            "task_type": task.task_type,
            "task_point": task.task_point,
            "is_completed": task.is_completed,
        } for task in tasks],
    }


def connection_snapshot(code, player_id):
    room = get_member_room(code, player_id)
    return RoomSerializer(room).data, own_start_data(room, player_id)
