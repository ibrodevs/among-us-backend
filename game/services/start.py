from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from game.physics import MAP
from game.maps import get_map
from game.settings import settings_for
from game.tasks import assign_tasks
from game.models import TaskAssignment
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
    members = list(
        RoomMembership.objects.select_for_update()
        .filter(room=room)
        .order_by("joined_at", "pk")
    )
    player_ids = [member.player_id for member in members]
    if player.pk not in player_ids or room.host_id != player.pk:
        raise PermissionDenied("Only the room host can start the game")
    if (
        room.status != Room.Status.WAITING
        or GameSession.objects.filter(room=room).exists()
    ):
        raise StartConflict()
    if len(members) < 4:
        raise StartConflict("At least 4 players required")
    if len(members) > min(room.max_players, 10):
        raise StartConflict("Too many players in room")

    roles = assign_roles(player_ids)
    now = timezone.now()
    options = settings_for(room)
    version = options["map_version"]
    mode = (
        options["area"]
        if options["area"] != "auto"
        else ("compact" if len(members) < 8 else "full")
    )
    game = GameSession.objects.create(
        room=room,
        last_tick_at=now,
        map_version=version,
        map_mode=mode,
        settings=options if version == 2 else {},
    )
    spawns = get_map(version)["spawns"]
    points = [(p["x"], p["y"]) for p in spawns] if version == 2 else SPAWN_POINTS
    PlayerGameState.objects.bulk_create(
        [
            PlayerGameState(
                game=game,
                player_id=player_id,
                role=roles[player_id],
                x=point[0],
                y=point[1],
                kill_available_at=now + timedelta(seconds=options["kill_cooldown"]),
            )
            for player_id, point in zip(player_ids, points)
        ]
    )
    if version == 2:
        assign_tasks(game, [pid for pid in player_ids if roles[pid] == "crew"])
        if options["special_roles"]:
            crew = list(game.player_states.filter(role="crew").order_by("player_id"))
            for state, role in zip(crew, ["technician", "medic", "tracker"]):
                state.special_role = role
                state.save(update_fields=["special_role"])
            state = game.player_states.filter(role="impostor").first()
            state.special_role = "mimic"
            state.save(update_fields=["special_role"])
        chosen = {m.player_id: m.color for m in members if m.color is not None}
        free = iter(c for c in range(10) if c not in chosen.values())
        for state in game.player_states.order_by("player_id"):
            state.color = (
                chosen[state.player_id] if state.player_id in chosen else next(free)
            )
            state.save(update_fields=["color"])
    else:
        TaskAssignment.objects.bulk_create(
            [
                TaskAssignment(
                    game=game, player_id=pid, task_type=t["type"], task_point=t["point"]
                )
                for pid in player_ids
                if roles[pid] == "crew"
                for t in MAP["tasks"]
            ]
        )
    room.status = Room.Status.PLAYING
    room.save(update_fields=["status"])
    room_data = RoomSerializer(room).data
    transaction.on_commit(lambda: publish_start(room_data, player_ids))
    return room_data
