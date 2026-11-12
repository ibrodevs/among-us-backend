import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import DatabaseError
from rest_framework.exceptions import AuthenticationFailed

from game.services.events import TRANSPORT_ERRORS, player_group, room_group
from game.services.snapshots import connection_snapshot, get_member_room

logger = logging.getLogger(__name__)
SERVICE_ERRORS = (DatabaseError, *TRANSPORT_ERRORS)


class RoomConsumer(AsyncJsonWebsocketConsumer):
    AUTH_TIMEOUT_SECONDS = 10
    MAX_FRAME_BYTES = 16384

    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["code"]
        self.player_id = None
        self.joined_groups = []
        await self.accept()
        self.auth_timeout = asyncio.create_task(self._expire_unauthenticated())

    async def _expire_unauthenticated(self):
        await asyncio.sleep(self.AUTH_TIMEOUT_SECONDS)
        if self.player_id is None:
            await self._error("UNAUTHORIZED", "Authenticate first", close_code=4401)

    async def _error(self, code, detail, *, close_code=None):
        await self.send_json({"type": "error", "code": code, "detail": detail})
        if close_code is not None:
            await self.close(code=close_code)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if text_data is None:
            await self._error("BAD_PAYLOAD", "JSON text required", close_code=4400)
            return
        if len(text_data.encode("utf-8")) > self.MAX_FRAME_BYTES:
            await self._error("BAD_PAYLOAD", "Message too large", close_code=1009)
            return
        try:
            content = json.loads(text_data)
        except (ValueError, RecursionError):
            await self._error("BAD_PAYLOAD", "Invalid JSON", close_code=4400)
            return
        await self.receive_json(content)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or not isinstance(content.get("type"), str):
            if self.player_id is None:
                await self._error("UNAUTHORIZED", "Authenticate first", close_code=4401)
            else:
                await self._error("BAD_PAYLOAD", "Message must contain a type")
            return
        msg_type = content["type"]
        if self.player_id is None:
            if msg_type != "auth" or not isinstance(content.get("token"), str):
                await self._error("UNAUTHORIZED", "Authenticate first", close_code=4401)
                return
            try:
                self.player_id = await self._authenticate(content["token"])
                self.auth_timeout.cancel()
                # Subscribe before reading state: a concurrent start is either
                # in this snapshot or queued as an event after auth.ok.
                for group in (room_group(self.room_code), player_group(self.room_code, self.player_id)):
                    await self.channel_layer.group_add(group, self.channel_name)
                    self.joined_groups.append(group)
                room_data, own_data = await self._snapshot()
                await self.send_json({"type": "auth.ok", "player_id": self.player_id})
                await self.send_json({"type": "room.snapshot", "room": room_data})
                if own_data is not None:
                    await self.send_json(own_data)
            except AuthenticationFailed:
                await self._error("UNAUTHORIZED", "Invalid guest or room", close_code=4401)
            except SERVICE_ERRORS:
                await self._error("SERVICE_UNAVAILABLE", "Service temporarily unavailable", close_code=1013)
            return

        if msg_type == "auth":
            await self._error("ALREADY_AUTHENTICATED", "Open a new connection to authenticate again")
        elif msg_type == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self._error("NOT_IMPLEMENTED", "Game actions are not implemented in stage A")

    async def room_snapshot(self, event):
        await self._send_current_state(private=False)

    async def game_started(self, event):
        # Ignore event payloads: role and tasks only come from this socket's
        # authenticated identity, never from a caller-supplied player ID.
        await self._send_current_state(private=True)

    async def _send_current_state(self, *, private):
        if self.player_id is None:
            return
        try:
            room_data, own_data = await self._snapshot()
            if private:
                if own_data is not None:
                    await self.send_json(own_data)
            else:
                await self.send_json({"type": "room.snapshot", "room": room_data})
        except AuthenticationFailed:
            await self._error("UNAUTHORIZED", "Invalid guest or room", close_code=4401)
        except SERVICE_ERRORS:
            await self._error("SERVICE_UNAVAILABLE", "Service temporarily unavailable", close_code=1013)

    @database_sync_to_async
    def _authenticate(self, token):
        from players.authentication import validate_guest_token
        from rooms.models import RoomMembership

        player = validate_guest_token(token)
        room = get_member_room(self.room_code, player.pk)
        RoomMembership.objects.filter(room=room, player=player).update(is_connected=True)
        return str(player.pk)

    @database_sync_to_async
    def _snapshot(self):
        return connection_snapshot(self.room_code, self.player_id)

    @database_sync_to_async
    def _disconnect_member(self):
        from rooms.models import RoomMembership

        RoomMembership.objects.filter(room__code=self.room_code, player_id=self.player_id).update(is_connected=False)

    async def disconnect(self, close_code):
        self.auth_timeout.cancel()
        for group in self.joined_groups:
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except TRANSPORT_ERRORS:
                logger.warning("Connection group cleanup unavailable")
        if self.player_id is not None:
            try:
                await self._disconnect_member()
            except DatabaseError:
                logger.warning("Connection presence update unavailable")
