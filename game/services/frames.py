"""Bounded, process-local observer frames. Private views never enter Redis.

The caller holds one repeatable-read transaction. Context is loaded once per
state version / 100ms time bucket, then each observer is filtered independently.
Membership authorization is checked by the consumer before consulting this cache.
"""

import time
from collections import OrderedDict
from game.models import MeetingMessage
from rooms.models import RoomMembership

_FRAMES = OrderedDict()


def context_for(game):
    states = list(game.player_states.select_related("player").order_by("player_id"))
    tasks = list(game.tasks.order_by("task_point"))
    meeting = (
        game.meetings.filter(finished_at__isnull=True).first()
        if game.phase == "meeting"
        else None
    )
    return dict(
        states=states,
        tasks=tasks,
        members=set(
            RoomMembership.objects.filter(room_id=game.room_id).values_list(
                "player_id", flat=True
            )
        ),
        corpses=list(game.corpses.all()),
        incidents=list(game.sabotages.filter(status__in=["active", "repairing"])),
        doors=list(game.doors.all()),
        meeting=meeting,
        votes=list(meeting.votes.all()) if meeting else [],
        messages=(
            list(
                MeetingMessage.objects.filter(meeting=meeting)
                .select_related("player")
                .order_by("-created_at")[:100]
            )
            if meeting
            else []
        ),
    )


def observer_frame(game, player_id, public_builder=None, private_builder=None):
    key = (str(game.pk), game.state_version, int(time.monotonic() * 10))
    frame = _FRAMES.get(key)
    if frame is None:
        game._frame = context_for(game)
        frame = (game, {})
        _FRAMES[key] = frame
        while len(_FRAMES) > 32:
            _FRAMES.popitem(last=False)
    else:
        _FRAMES.move_to_end(key)
    frozen, views = frame
    player_id = str(player_id)
    if player_id not in views:
        from game.services.simulation import public_snapshot, private_snapshot

        views[player_id] = (
            (public_builder or public_snapshot)(frozen, viewer_id=player_id),
            (private_builder or private_snapshot)(frozen, player_id),
        )
    return views[player_id]
