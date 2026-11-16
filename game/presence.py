from django.db.models import Exists, OuterRef
from django.utils import timezone
from game.models import ConnectionLease
from rooms.models import RoomMembership


def expire_connections(now=None):
    now = now or timezone.now()
    ConnectionLease.objects.filter(expires_at__lt=now).delete()
    live = ConnectionLease.objects.filter(
        room_id=OuterRef("room_id"), player_id=OuterRef("player_id"), expires_at__gt=now
    )
    RoomMembership.objects.annotate(has_live=Exists(live)).filter(
        is_connected=True, has_live=False
    ).update(is_connected=False)
