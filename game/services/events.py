import logging

from asgiref.sync import async_to_sync
from channels.exceptions import ChannelFull
from channels.layers import get_channel_layer
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)
TRANSPORT_ERRORS = (RedisError, ChannelFull, OSError, TimeoutError)


def room_group(code):
    return "room_" + code


def player_group(code, player_id):
    return f"game_{code}_player_{player_id}"


async def _publish_start(room_data, player_ids):
    layer = get_channel_layer()
    await layer.group_send(room_group(room_data["code"]), {"type": "room.snapshot", "room": room_data})
    for player_id in player_ids:
        # A notification only. The authenticated consumer loads its own state.
        # Even the private channel-layer event carries no roles or tokens.
        await layer.group_send(player_group(room_data["code"], player_id), {"type": "game.started"})


def publish_start(room_data, player_ids):
    """Run after commit. Transport failure cannot undo a committed match."""
    try:
        async_to_sync(_publish_start)(room_data, player_ids)
    except TRANSPORT_ERRORS:
        logger.warning("Start notification unavailable; clients can recover through authenticated reconnect")
