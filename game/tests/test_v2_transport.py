from unittest.mock import patch
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.db import close_old_connections, connection
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter
from game.tests.helpers import make_room, MEMORY_CHANNEL_LAYERS
from game.routing import websocket_urlpatterns
from game.services.start import start_game
from game.services.simulation import public_snapshot, command, RuleError
from game.services.transport import publish_update
from game.maps import game_map
from game.v2 import appearance_id
from players.authentication import create_guest_token
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
class AsterionSocketTests(TransactionTestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.room.settings = {"map_version": 2}
        self.room.save()
        with patch("game.services.start.publish_start"):
            start_game(code=self.room.code, player=self.players[0])
        self.game = self.room.game
        self.crew = self.game.player_states.filter(role="crew").first()
        self.imp = self.game.player_states.get(role="impostor")
        self.imp.x, self.imp.y = 650, 1230
        self.imp.save()
        self.crew_token = create_guest_token(self.crew.player)
        self.imp_token = create_guest_token(self.imp.player)

    async def connect_as(self, token, version=2):
        ws = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), f"/ws/rooms/{self.room.code}/"
        )
        await ws.connect()
        await ws.send_json_to(
            {"type": "auth", "token": token, "protocol_version": version}
        )
        self.assertEqual((await ws.receive_json_from())["type"], "auth.ok")
        self.assertEqual((await ws.receive_json_from())["type"], "room.snapshot")
        self.assertEqual((await ws.receive_json_from())["type"], "game.started")
        return ws

    async def test_actual_socket_filters_hidden_actor_and_requires_upgrade(self):
        ws = await self.connect_as(self.crew_token)
        try:
            snapshot = await ws.receive_json_from()
            own = await ws.receive_json_from()
            self.assertEqual(snapshot["protocol_version"], 2)
            self.assertEqual(own["role"], "crew")
            self.assertNotIn(
                appearance_id(self.game, self.imp),
                [p["id"] for p in snapshot["players"]],
            )
            self.assertNotIn("initiator", json.dumps(snapshot))
        finally:
            await ws.disconnect()
        old = await self.connect_as(self.crew_token, 1)
        try:
            self.assertEqual(
                (await old.receive_json_from())["code"], "UPGRADE_REQUIRED"
            )
        finally:
            await old.disconnect()

    async def test_task_event_is_private_and_room_bus_only_invalidates(self):
        def prepare():
            task = self.game.tasks.filter(player_id=self.crew.player_id).first()
            point = next(
                t for t in game_map(self.game)["tasks"] if t["point"] == task.task_point
            )
            self.crew.x, self.crew.y = point["x"], point["y"]
            self.crew.save()
            return str(task.pk)

        task_id = await database_sync_to_async(prepare)()
        crew = await self.connect_as(self.crew_token)
        other = await self.connect_as(self.imp_token)
        try:
            for ws in [crew, other]:
                await ws.receive_json_from()
                await ws.receive_json_from()
                for _ in range(4):
                    await ws.receive_json_from()
            await crew.send_json_to({"type": "task.begin", "task_id": task_id})
            self.assertEqual((await crew.receive_json_from())["type"], "game.self")
            self.assertEqual((await crew.receive_json_from())["type"], "task.challenge")
            received = [
                await other.receive_json_from(),
                await other.receive_json_from(),
            ]
            self.assertEqual(
                [m["type"] for m in received], ["game.snapshot", "game.self"]
            )
            self.assertNotIn(task_id, json.dumps(received))
        finally:
            await crew.disconnect()
            await other.disconnect()


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
@skipUnlessDBFeature("has_select_for_update")
class AsterionRaceTests(TransactionTestCase):
    def test_parallel_critical_sabotages_commit_exactly_one(self):
        room, players = make_room(10)
        room.settings = {"map_version": 2}
        room.save()
        with patch("game.services.start.publish_start"):
            start_game(code=room.code, player=players[0])
        actors = list(room.game.player_states.filter(role="impostor"))
        barrier = Barrier(2)

        def act(actor, kind):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                command(
                    room.code, actor.player_id, {"type": "sabotage.start", "kind": kind}
                )
                return "ok"
            except RuleError as e:
                return e.code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(act, a, k) for a, k in zip(actors, ["oxygen", "reactor"])
            ]
            outcomes = [f.result(timeout=15) for f in futures]
        self.assertEqual(sorted(outcomes), ["COOLDOWN", "ok"])
        self.assertEqual(room.game.sabotages.count(), 1)
