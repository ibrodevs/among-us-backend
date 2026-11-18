import time
import logging
import signal
import os
import json
from pathlib import Path
from threading import Event
from game.worker_leader import ClockLeader
from game import metrics
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
        self.stdout.write("CREWMATE X game clock started (10 Hz)")
        cleanup = 0
        stopping = Event()

        def stop(*_):
            stopping.set()

        old_handlers = {
            sig: signal.signal(sig, stop) for sig in [signal.SIGTERM, signal.SIGINT]
        }
        leader = ClockLeader()
        leading = False
        last_check = 0
        frames = 0
        epoch = time.monotonic()
        health = Path(
            os.getenv("WORKER_HEALTH_FILE", "/tmp/crewmate-x-worker-health.json")
        )
        last_health = 0
        try:
            while not stopping.is_set():
                started = time.monotonic()
                if not leading or started - last_check > 2:
                    leading = leader.acquire()
                    last_check = started
                if started - last_health >= 1:
                    try:
                        temporary = health.with_suffix(".tmp")
                        temporary.write_text(
                            json.dumps(
                                dict(at=time.time(), pid=os.getpid(), leader=leading)
                            )
                        )
                        temporary.replace(health)
                    except OSError:
                        logging.getLogger(__name__).warning(
                            "Worker heartbeat file unavailable"
                        )
                    last_health = started
                if not leading:
                    stopping.wait(1)
                    continue
                close_old_connections()
                queries = [0]

                def sql(execute, sql, params, many, context):
                    queries[0] += 1
                    return execute(sql, params, many, context)

                try:
                    from django.db import connection

                    with connection.execute_wrapper(sql):
                        codes = list(active_room_codes())
                        for code in codes:
                            if stopping.is_set():
                                break
                            began = time.monotonic()
                            previous_queries = queries[0]
                            snapshot, events = tick(code, invalidation_only=True)
                            publishing = time.monotonic()
                            metrics.record("tick_ms", (publishing - began) * 1000)
                            metrics.record("tick_sql", queries[0] - previous_queries)
                            publish_update(
                                code, snapshot, events, refresh_private=bool(snapshot)
                            )
                            if snapshot:
                                metrics.record(
                                    "publish_ms", (time.monotonic() - publishing) * 1000
                                )
                        if started - cleanup > 15:
                            expire_connections()
                            cleanup = started
                    frames += 1
                    metrics.record("cycle_sql", queries[0])
                    metrics.record("cycle_ms", (time.monotonic() - started) * 1000)
                    metrics.flush(
                        "worker",
                        leader=True,
                        cycles=frames,
                        hz=frames / max(0.001, time.monotonic() - epoch),
                        activeRooms=len(codes),
                    )
                except DatabaseError:
                    logging.getLogger(__name__).exception(
                        "Game clock database unavailable"
                    )
                stopping.wait(max(0.001, 0.1 - (time.monotonic() - started)))
        finally:
            leader.close()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            try:
                health.unlink(missing_ok=True)
            except OSError:
                pass
            self.stdout.write("CREWMATE X game clock stopped cleanly")
