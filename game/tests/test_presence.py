from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter
from django.test import TransactionTestCase, override_settings
from game.routing import websocket_urlpatterns
from game.tests.helpers import make_room, MEMORY_CHANNEL_LAYERS
from players.authentication import create_guest_token
from rooms.models import RoomMembership
from game.models import ConnectionLease


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
class PresenceTests(TransactionTestCase):
    def setUp(self):
        self.room, self.players = make_room()

    async def test_two_tabs_old_disconnect_does_not_clear_new_presence(self):
        sockets = []
        try:
            for _ in range(2):
                ws = WebsocketCommunicator(
                    URLRouter(websocket_urlpatterns), f"/ws/rooms/{self.room.code}/"
                )
                await ws.connect()
                await ws.send_json_to(
                    {"type": "auth", "token": create_guest_token(self.players[0])}
                )
                await ws.receive_json_from()
                await ws.receive_json_from()
                sockets.append(ws)
            self.assertEqual(await ConnectionLease.objects.acount(), 2)
            await sockets[0].disconnect()
            self.assertTrue(
                (
                    await RoomMembership.objects.aget(
                        room=self.room, player=self.players[0]
                    )
                ).is_connected
            )
            await sockets[1].disconnect()
            self.assertFalse(
                (
                    await RoomMembership.objects.aget(
                        room=self.room, player=self.players[0]
                    )
                ).is_connected
            )
        finally:
            for ws in sockets:
                await ws.disconnect()

    def test_lease_in_another_room_does_not_keep_stale_membership_online(self):
        from datetime import timedelta
        from django.utils import timezone
        from game.presence import expire_connections
        from rooms.models import Room

        other = Room.objects.create(code="OTHER1", host=self.players[0])
        first = RoomMembership.objects.get(room=self.room, player=self.players[0])
        first.is_connected = True
        first.save()
        second = RoomMembership.objects.create(
            room=other, player=self.players[0], is_connected=True
        )
        ConnectionLease.objects.create(
            channel="live-other",
            room=other,
            player=self.players[0],
            expires_at=timezone.now() + timedelta(seconds=30),
        )
        expire_connections()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_connected)
        self.assertTrue(second.is_connected)
