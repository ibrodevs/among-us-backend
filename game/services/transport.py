from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from game.services.events import room_group, TRANSPORT_ERRORS
import logging


def publish_update(code, snapshot, events, refresh_private=False):
    if snapshot is None:
        return
    if snapshot.get("protocol_version") == 2:
        # Only invalidation crosses the room bus; each observer gets a filtered view.
        snapshot, events, refresh_private = (
            {"protocol_version": 2, "state_version": snapshot["state_version"]},
            [],
            True,
        )
    try:
        async_to_sync(get_channel_layer().group_send)(
            room_group(code),
            {
                "type": "game.update",
                "snapshot": snapshot,
                "events": events,
                "refresh_private": refresh_private,
            },
        )
    except TRANSPORT_ERRORS:
        logging.getLogger(__name__).warning(
            "Game transport unavailable; state persisted"
        )
