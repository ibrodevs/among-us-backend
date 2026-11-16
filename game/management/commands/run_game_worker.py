import time
import logging
from django.core.management.base import BaseCommand
from django.db import close_old_connections, DatabaseError
from django.db.models import Exists, OuterRef, Q
from rooms.models import RoomMembership
from game.models import GameSession, SabotageInstance, PlayerGameState
from game.presence import expire_connections
from game.services.simulation import tick
from game.services.transport import publish_update


def active_room_codes():
    """Idle abandoned rooms need no 10 Hz writes; durable deadlines still advance."""
    clients = RoomMembership.objects.filter(
        room_id=OuterRef("room_id"), is_connected=True
    )
    timed = SabotageInstance.objects.filter(
        game_id=OuterRef("pk"),
        status__in=["active", "repairing"],
        deadline_at__isnull=False,
    )
    technician = PlayerGameState.objects.filter(
        game_id=OuterRef("pk"), special_role="technician", is_in_vent=True
    )
    return (
        GameSession.objects.exclude(phase="finished")
        .annotate(
            has_clients=Exists(clients),
            has_deadline=Exists(timed),
            has_technician=Exists(technician),
        )
        .filter(
            Q(has_clients=True)
            | Q(has_deadline=True)
            | Q(has_technician=True)
            | Q(phase="meeting")
        )
        .values_list("room__code", flat=True)
    )


class Command(BaseCommand):
    help = "Run durable 10 Hz game clock; required alongside Daphne"

    def handle(self, *args, **options):
        self.stdout.write("Crew Mission game clock started (10 Hz)")
        cleanup = 0
        try:
            while True:
                started = time.monotonic()
                close_old_connections()
                try:
                    codes = list(active_room_codes())
                    for code in codes:
                        snapshot, events = tick(code)
                        publish_update(
                            code,
                            snapshot,
                            events,
                            refresh_private=bool(
                                snapshot
                                and (
                                    (snapshot["phase"] == "playing" and not events)
                                    or any(e["type"] != "player.moved" for e in events)
                                )
                            ),
                        )
                    if started - cleanup > 15:
                        expire_connections()
                        cleanup = started
                except DatabaseError:
                    logging.getLogger(__name__).exception(
                        "Game clock database unavailable"
                    )
                time.sleep(max(0.001, 0.1 - (time.monotonic() - started)))
        except KeyboardInterrupt:
            self.stdout.write("Game clock stopped")
