from rest_framework import serializers
from rooms.models import Room
from game.limits import MIN_PLAYERS, MAX_PLAYERS, minimum_players


class RoomCreateSerializer(serializers.Serializer):
    impostor_count = serializers.IntegerField(min_value=1, max_value=3, default=2)

    def validate(self, attrs):
        if attrs["max_players"] < minimum_players(attrs["impostor_count"]):
            raise serializers.ValidationError(
                "Вместимость меньше минимального состава для выбранного количества предателей"
            )
        return attrs

    max_players = serializers.IntegerField(
        min_value=MIN_PLAYERS, max_value=MAX_PLAYERS, default=MAX_PLAYERS
    )


class RoomJoinSerializer(serializers.Serializer):
    code = serializers.RegexField(regex=r"^[A-Z0-9]{6}$")


class RoomSerializer(serializers.ModelSerializer):
    min_players = serializers.IntegerField(read_only=True)
    host_player_id = serializers.UUIDField(source="host_id", read_only=True)
    players = serializers.SerializerMethodField()
    settings = serializers.SerializerMethodField()

    def get_settings(self, room):
        from game.settings import settings_for

        return settings_for(room)

    class Meta:
        model = Room
        fields = [
            "id",
            "code",
            "status",
            "min_players",
            "max_players",
            "host_player_id",
            "players",
            "created_at",
            "settings",
        ]

    def get_players(self, room: Room):
        memberships = room.memberships.select_related("player").order_by(
            "joined_at", "id"
        )
        return [
            {
                "id": str(m.player_id),
                "nickname": m.player.nickname,
                "is_host": m.player_id == room.host_id,
                "is_connected": m.is_connected,
                "is_ready": m.is_ready,
                "color": m.color,
            }
            for m in memberships
        ]
