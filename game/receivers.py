from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.dispatch import receiver

from game.services.events import TRANSPORT_ERRORS, room_group
from rooms.signals import lobby_changed


@receiver(lobby_changed)
def broadcast_lobby(sender, room_code, **kwargs):
    # A notification only; each consumer rechecks membership before delivery.
    try:
        async_to_sync(get_channel_layer().group_send)(room_group(room_code), {"type": "room.snapshot"})
    except TRANSPORT_ERRORS:
        import logging
        logging.getLogger(__name__).warning("Lobby notification unavailable")
