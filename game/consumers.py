import asyncio
import json
import logging
import time
from datetime import timedelta
from django.utils import timezone
from game.models import GameSession, ConnectionLease
from game.services.simulation import (
    command,
    RuleError,
    public_snapshot,
    private_snapshot,
)
from game.services.transport import publish_update

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
        self.command_times = []
        self.protocol_version = 1
        self.last_game_version = -1
        self.previous_public = None
        self.previous_own = None
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
                self.protocol_version = content.get("protocol_version", 1)
                self.player_id = await self._authenticate(content["token"])
                self.auth_timeout.cancel()
                # Subscribe before reading state: a concurrent start is either
                # in this snapshot or queued as an event after auth.ok.
                for group in (
                    room_group(self.room_code),
                    player_group(self.room_code, self.player_id),
                ):
                    await self.channel_layer.group_add(group, self.channel_name)
                    self.joined_groups.append(group)
                room_data, own_data = await self._snapshot()
                await self.send_json({"type": "auth.ok", "player_id": self.player_id})
                await self.send_json({"type": "room.snapshot", "room": room_data})
                if own_data is not None:
                    await self.send_json(own_data)
                    await self._send_game_state()
            except AuthenticationFailed:
                await self._error(
                    "UNAUTHORIZED", "Invalid guest or room", close_code=4401
                )
            except SERVICE_ERRORS:
                await self._error(
                    "SERVICE_UNAVAILABLE",
                    "Service temporarily unavailable",
                    close_code=1013,
                )
            return

        if msg_type == "auth":
            await self._error(
                "ALREADY_AUTHENTICATED", "Open a new connection to authenticate again"
            )
        elif msg_type == "ping":
            await self._renew_lease()
            await self.send_json({"type": "pong"})
        else:
            now = time.monotonic()
            self.command_times = [t for t in self.command_times if now - t < 1]
            if len(self.command_times) >= 20:
                await self._error("RATE_LIMITED", "Слишком много команд")
                return
            self.command_times.append(now)
            try:
                events, snapshot, own = await database_sync_to_async(command)(
                    self.room_code, self.player_id, content
                )
                if own is not None:
                    await self.send_json(own)
                    if own.get("protocol_version") == 2:
                        for event in events:
                            if event["type"] in ["task.challenge", "task.verified"]:
                                await self.send_json(
                                    {
                                        "protocol_version": 2,
                                        "game_id": own["game_id"],
                                        "state_version": own["state_version"],
                                        **event,
                                    }
                                )
                await database_sync_to_async(publish_update)(
                    self.room_code, snapshot, events, True
                )
            except RuleError as error:
                await self._error(error.code, error.detail)
            except SERVICE_ERRORS:
                logger.exception("Game action unavailable")
                await self._error(
                    "SERVICE_UNAVAILABLE", "Service temporarily unavailable"
                )

    async def room_snapshot(self, event):
        await self._send_current_state(private=False)

    async def game_started(self, event):
        # Ignore event payloads: role and tasks only come from this socket's
        # authenticated identity, never from a caller-supplied player ID.
        await self._send_current_state(private=True)
        await self._send_game_state()

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
            await self._error(
                "SERVICE_UNAVAILABLE",
                "Service temporarily unavailable",
                close_code=1013,
            )

    @database_sync_to_async
    def _authenticate(self, token):
        from players.authentication import validate_guest_token
        from rooms.models import RoomMembership

        player = validate_guest_token(token)
        room = get_member_room(self.room_code, player.pk)
        ConnectionLease.objects.update_or_create(
            channel=self.channel_name,
            defaults={
                "room": room,
                "player": player,
                "expires_at": timezone.now() + timedelta(seconds=45),
            },
        )
        RoomMembership.objects.filter(room=room, player=player).update(
            is_connected=True
        )
        return str(player.pk)

    @database_sync_to_async
    def _snapshot(self):
        return connection_snapshot(self.room_code, self.player_id)

    @database_sync_to_async
    def _disconnect_member(self):
        from rooms.models import RoomMembership

        ConnectionLease.objects.filter(channel=self.channel_name).delete()
        if not ConnectionLease.objects.filter(
            room__code=self.room_code,
            player_id=self.player_id,
            expires_at__gt=timezone.now(),
        ).exists():
            RoomMembership.objects.filter(
                room__code=self.room_code, player_id=self.player_id
            ).update(is_connected=False)

    @database_sync_to_async
    def _renew_lease(self):
        ConnectionLease.objects.filter(channel=self.channel_name).update(
            expires_at=timezone.now() + timedelta(seconds=45)
        )

    @database_sync_to_async
    def _game_state(self):
        get_member_room(self.room_code, self.player_id)
        game = GameSession.objects.filter(room__code=self.room_code).first()
        return (
            (
                public_snapshot(game, viewer_id=self.player_id),
                private_snapshot(game, self.player_id),
            )
            if game
            else (None, None)
        )

    async def _send_game_state(self):
        try:
            public, own = await self._game_state()
            if public:
                if public.get("protocol_version") == 2 and self.protocol_version != 2:
                    await self._error(
                        "UPGRADE_REQUIRED",
                        "Update the client for Asterion",
                        close_code=4406,
                    )
                    return
                self.last_game_version = public["state_version"]
                await self.send_json(public)
                await self.send_json(own)
                if public.get("protocol_version") == 2:
                    from game.observer_events import changes

                    for event in changes(
                        self.previous_public, public, self.previous_own, own
                    ):
                        await self.send_json(event)
                    self.previous_public, self.previous_own = public, own
        except AuthenticationFailed:
            await self._error("UNAUTHORIZED", "Invalid guest or room", close_code=4401)
        except SERVICE_ERRORS:
            await self._error(
                "SERVICE_UNAVAILABLE",
                "Service temporarily unavailable",
                close_code=1013,
            )

    async def game_update(self, event):
        try:
            if event["snapshot"].get("protocol_version") == 2:
                if event["snapshot"].get("state_version", 0) > self.last_game_version:
                    await self._send_game_state()
                return
            await database_sync_to_async(get_member_room)(
                self.room_code, self.player_id
            )
            for item in event["events"]:
                await self.send_json({"protocol_version": 1, **item})
            await self.send_json(event["snapshot"])
            if event.get("refresh_private"):
                _, own = await self._game_state()
                await self.send_json(own)
        except AuthenticationFailed:
            await self._error("UNAUTHORIZED", "Invalid guest or room", close_code=4401)
        except SERVICE_ERRORS:
            await self._error(
                "SERVICE_UNAVAILABLE",
                "Service temporarily unavailable",
                close_code=1013,
            )

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
