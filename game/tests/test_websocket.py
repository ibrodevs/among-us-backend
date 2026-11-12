from unittest.mock import AsyncMock, patch

from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.db import DatabaseError
from django.test import TransactionTestCase, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError

from game.consumers import RoomConsumer
from game.models import GameSession, PlayerGameState, TaskAssignment
from game.routing import websocket_urlpatterns
from game.services.events import player_group, room_group
from game.services.start import start_game
from game.tests.helpers import MEMORY_CHANNEL_LAYERS, make_room
from players.authentication import create_guest_token
from players.models import Player
from rooms.models import RoomMembership

application = URLRouter(websocket_urlpatterns)


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
class RoomWebsocketTests(TransactionTestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.tokens = [create_guest_token(player) for player in self.players]

    async def connect(self, code=None):
        ws = WebsocketCommunicator(application, f"/ws/rooms/{code or self.room.code}/")
        connected, _ = await ws.connect()
        self.assertTrue(connected)
        return ws

    async def auth(self, ws, index=0):
        await ws.send_json_to({"type": "auth", "token": self.tokens[index]})
        self.assertEqual(await ws.receive_json_from(), {"type": "auth.ok", "player_id": str(self.players[index].pk)})
        public = await ws.receive_json_from()
        self.assertEqual(public["type"], "room.snapshot")
        self.assert_public(public)
        return public

    def assert_public(self, value):
        if isinstance(value, dict):
            self.assertFalse({"role", "roles", "role_map", "token", "tasks"}.intersection(value))
            for item in value.values():
                self.assert_public(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_public(item)

    async def start(self):
        return await database_sync_to_async(start_game)(code=self.room.code, player=self.players[0])

    async def test_four_sockets_receive_only_their_own_roles_and_no_public_leaks(self):
        sockets = []
        layer = get_channel_layer()
        try:
            for index in range(4):
                ws = await self.connect()
                sockets.append(ws)
                self.assertEqual((await self.auth(ws, index))["room"]["status"], "waiting")
            with patch.object(layer, "group_send", wraps=layer.group_send) as send:
                await self.start()
                for index, ws in enumerate(sockets):
                    public = await ws.receive_json_from()
                    self.assert_public(public)
                    self.assertEqual(public["room"]["status"], "playing")
                    private = await ws.receive_json_from()
                    self.assertEqual(private["type"], "game.started")
                    state = await PlayerGameState.objects.aget(player=self.players[index], game__room=self.room)
                    self.assertEqual(private["role"], state.role)
                    self.assertEqual(private["tasks"], [])
                    self.assertEqual(private["room_code"], self.room.code)
                    self.assertEqual(private["game_id"], str(state.game_id))
                    self.assertEqual(private["state_version"], 1)
                    self.assertNotIn("roles", private)
                    self.assertNotIn("players", private)
                    self.assertNotIn("token", private)
                    self.assertTrue(await ws.receive_nothing(timeout=0.02))
                self.assertEqual(send.call_count, 5)
                self.assertEqual(send.call_args_list[0].args[0], room_group(self.room.code))
                for call in send.call_args_list:
                    self.assert_public(call.args[1])
                self.assertEqual(
                    {call.args[0] for call in send.call_args_list[1:]},
                    {player_group(self.room.code, p.pk) for p in self.players},
                )
        finally:
            for ws in sockets:
                await ws.disconnect()

    async def test_offline_reconnect_uses_same_database_role_and_only_own_tasks(self):
        await self.start()
        game = await GameSession.objects.aget(room=self.room)
        task = await TaskAssignment.objects.acreate(game=game, player=self.players[0], task_type="wires", task_point="console-a")
        other = await TaskAssignment.objects.acreate(game=game, player=self.players[1], task_type="wires", task_point="secret-other-console")
        first_state = None
        for _ in range(2):
            ws = await self.connect()
            try:
                public = await self.auth(ws)
                self.assertEqual(public["room"]["status"], "playing")
                own = await ws.receive_json_from()
                self.assertEqual(own["type"], "game.started")
                self.assertEqual([t["id"] for t in own["tasks"]], [str(task.pk)])
                self.assertNotIn(str(other.pk), str(own))
                if first_state is None:
                    first_state = own
                else:
                    self.assertEqual(own, first_state)
            finally:
                await ws.disconnect()
        self.assertEqual(await PlayerGameState.objects.acount(), 4)
        self.assertEqual(await GameSession.objects.acount(), 1)

    async def test_private_group_reaches_only_its_owner(self):
        await self.start()
        first, second = await self.connect(), await self.connect()
        try:
            await self.auth(first, 0)
            await first.receive_json_from()
            await self.auth(second, 1)
            await second.receive_json_from()
            await get_channel_layer().group_send(player_group(self.room.code, self.players[0].pk), {"type": "game.started"})
            self.assertEqual((await first.receive_json_from())["type"], "game.started")
            self.assertTrue(await second.receive_nothing(timeout=0.02))
        finally:
            await first.disconnect()
            await second.disconnect()

    async def test_unauthenticated_socket_does_not_receive_start(self):
        ws = await self.connect()
        try:
            await self.start()
            self.assertTrue(await ws.receive_nothing(timeout=0.02))
        finally:
            await ws.disconnect()

    async def assert_auth_rejected(self, token, code=None):
        ws = await self.connect(code)
        try:
            await ws.send_json_to({"type": "auth", "token": token})
            error = await ws.receive_json_from()
            self.assertEqual(error["code"], "UNAUTHORIZED")
            self.assertEqual((await ws.receive_output())["code"], 4401)
        finally:
            await ws.disconnect()

    async def test_bad_expired_and_non_member_tokens_and_missing_room(self):
        await self.assert_auth_rejected("invalid")
        outsider = await Player.objects.acreate(nickname="Outsider")
        await self.assert_auth_rejected(create_guest_token(outsider))
        await self.assert_auth_rejected(self.tokens[0], "ZZZ999")
        with patch("django.core.signing.time.time", return_value=1):
            expired = create_guest_token(self.players[0])
        await self.assert_auth_rejected(expired)

    async def test_auth_cannot_switch_identity(self):
        await self.start()
        ws = await self.connect()
        try:
            await self.auth(ws)
            own = await ws.receive_json_from()
            await ws.send_json_to({"type": "auth", "token": self.tokens[1]})
            self.assertEqual((await ws.receive_json_from())["code"], "ALREADY_AUTHENTICATED")
            await get_channel_layer().group_send(player_group(self.room.code, self.players[1].pk), {"type": "game.started"})
            self.assertTrue(await ws.receive_nothing(timeout=0.02))
            await get_channel_layer().group_send(player_group(self.room.code, self.players[0].pk), {"type": "game.started"})
            self.assertEqual(await ws.receive_json_from(), own)
        finally:
            await ws.disconnect()

    async def test_first_frame_must_authenticate(self):
        ws = await self.connect()
        try:
            await ws.send_json_to({"type": "ping"})
            self.assertEqual((await ws.receive_json_from())["code"], "UNAUTHORIZED")
            self.assertEqual((await ws.receive_output())["code"], 4401)
        finally:
            await ws.disconnect()

    async def test_malformed_and_oversized_frames(self):
        for payload, close_code in (("{broken", 4400), ("x" * (RoomConsumer.MAX_FRAME_BYTES + 1), 1009)):
            ws = await self.connect()
            try:
                await ws.send_to(text_data=payload)
                self.assertEqual((await ws.receive_json_from())["code"], "BAD_PAYLOAD")
                self.assertEqual((await ws.receive_output())["code"], close_code)
            finally:
                await ws.disconnect()

    async def test_invalid_message_shape_and_stage_b_actions(self):
        ws = await self.connect()
        try:
            await self.auth(ws)
            for payload in ([], None, {"type": 10}, {}):
                await ws.send_json_to(payload)
                self.assertEqual((await ws.receive_json_from())["code"], "BAD_PAYLOAD")
            for kind in ("player.move", "player.kill", "task.complete", "body.report", "meeting.call", "vote.cast", "unknown"):
                await ws.send_json_to({"type": kind})
                self.assertEqual((await ws.receive_json_from())["code"], "NOT_IMPLEMENTED")
            await ws.send_json_to({"type": "ping"})
            self.assertEqual(await ws.receive_json_from(), {"type": "pong"})
        finally:
            await ws.disconnect()

    async def test_authentication_timeout(self):
        with patch.object(RoomConsumer, "AUTH_TIMEOUT_SECONDS", 0.02):
            ws = await self.connect()
            try:
                self.assertEqual((await ws.receive_json_from())["code"], "UNAUTHORIZED")
                self.assertEqual((await ws.receive_output())["code"], 4401)
            finally:
                await ws.disconnect()

    async def test_membership_rechecked_before_private_delivery(self):
        ws = await self.connect()
        try:
            await self.auth(ws)
            await RoomMembership.objects.filter(room=self.room, player=self.players[0]).adelete()
            await get_channel_layer().group_send(player_group(self.room.code, self.players[0].pk), {"type": "game.started"})
            self.assertEqual((await ws.receive_json_from())["code"], "UNAUTHORIZED")
            self.assertEqual((await ws.receive_output())["code"], 4401)
        finally:
            await ws.disconnect()

    async def test_auth_database_and_redis_failures_are_safe(self):
        cases = (
            patch.object(RoomConsumer, "_authenticate", AsyncMock(side_effect=DatabaseError("secret database details"))),
            patch.object(get_channel_layer(), "group_add", AsyncMock(side_effect=RedisConnectionError("secret transport details"))),
        )
        for failure in cases:
            ws = await self.connect()
            try:
                with failure:
                    await ws.send_json_to({"type": "auth", "token": self.tokens[0]})
                    self.assertEqual(await ws.receive_json_from(), {"type": "error", "code": "SERVICE_UNAVAILABLE", "detail": "Service temporarily unavailable"})
                    self.assertEqual((await ws.receive_output())["code"], 1013)
            finally:
                await ws.disconnect()

    async def test_start_during_auth_group_subscription_is_replayed(self):
        layer = get_channel_layer()
        original = layer.group_add
        started = False

        async def start_between_subscriptions(group, channel):
            nonlocal started
            await original(group, channel)
            if not started:
                started = True
                await self.start()

        ws = await self.connect()
        try:
            with patch.object(layer, "group_add", side_effect=start_between_subscriptions):
                self.assertEqual((await self.auth(ws))["room"]["status"], "playing")
                self.assertEqual((await ws.receive_json_from())["type"], "game.started")
        finally:
            await ws.disconnect()
