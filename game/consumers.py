from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.exceptions import AuthenticationFailed


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["code"]
        self.player_id = None
        self.room_group = "room_" + self.room_code
        await self.accept()

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if self.player_id is None:
            if msg_type != "auth" or not isinstance(content.get("token"), str):
                await self.send_json({"type": "error", "code": "UNAUTHORIZED", "detail": "Authenticate first"})
                await self.close(code=4401)
                return
            try:
                player_id, room_data = await self._authenticate(content["token"])
            except AuthenticationFailed:
                await self.send_json({"type": "error", "code": "UNAUTHORIZED", "detail": "Invalid guest or room"})
                await self.close(code=4401)
                return
            self.player_id = player_id
            await self.channel_layer.group_add(self.room_group, self.channel_name)
            await self.send_json({"type": "auth.ok", "player_id": player_id})
            await self.send_json({"type": "room.snapshot", "room": room_data})
            return

        if msg_type == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self.send_json({"type": "error", "code": "NOT_IMPLEMENTED", "detail": "Game actions are not implemented yet"})

    @database_sync_to_async
    def _authenticate(self, token):
        from players.authentication import validate_guest_token
        from rooms.models import RoomMembership
        from rooms.serializers import RoomSerializer
        from rooms.models import Room

        player = validate_guest_token(token)
        try:
            room = Room.objects.get(code=self.room_code)
        except Room.DoesNotExist:
            raise AuthenticationFailed("Room does not exist")
        if not RoomMembership.objects.filter(room=room, player=player).exists():
            raise AuthenticationFailed("Player is not in room")
        RoomMembership.objects.filter(room=room, player=player).update(is_connected=True)
        return str(player.pk), RoomSerializer(room).data

    @database_sync_to_async
    def _disconnect_member(self):
        from rooms.models import RoomMembership
        RoomMembership.objects.filter(room__code=self.room_code, player_id=self.player_id).update(is_connected=False)

    async def disconnect(self, close_code):
        if self.player_id is not None:
            await self.channel_layer.group_discard(self.room_group, self.channel_name)
            await self._disconnect_member()
