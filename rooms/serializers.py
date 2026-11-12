from rest_framework import serializers
from rooms.models import Room


class RoomCreateSerializer(serializers.Serializer):
    max_players = serializers.IntegerField(min_value=4, max_value=10, default=10)


class RoomJoinSerializer(serializers.Serializer):
    code = serializers.RegexField(regex=r"^[A-Z0-9]{6}$")


class RoomSerializer(serializers.ModelSerializer):
    min_players = serializers.IntegerField(read_only=True)
    host_player_id = serializers.UUIDField(source="host_id", read_only=True)
    players = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ["id", "code", "status", "min_players", "max_players", "host_player_id", "players", "created_at"]

    def get_players(self, room: Room):
        memberships = room.memberships.select_related("player").order_by("joined_at")
        return [{
            "id": str(m.player_id),
            "nickname": m.player.nickname,
            "is_host": m.player_id == room.host_id,
            "is_connected": m.is_connected,
        } for m in memberships]
