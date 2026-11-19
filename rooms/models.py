import uuid
from django.db import models
from players.models import Player
from game.limits import MIN_PLAYERS, MAX_PLAYERS, PLAYER_COLORS, minimum_players


class Room(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        PLAYING = "playing", "Playing"
        MEETING = "meeting", "Meeting"
        FINISHED = "finished", "Finished"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=6, unique=True, db_index=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.WAITING
    )
    host = models.ForeignKey(
        Player, on_delete=models.PROTECT, related_name="hosted_rooms"
    )
    max_players = models.PositiveSmallIntegerField(default=MAX_PLAYERS)
    settings = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    max_players__gte=MIN_PLAYERS, max_players__lte=MAX_PLAYERS
                ),
                name="valid_room_capacity",
            )
        ]

    @property
    def min_players(self) -> int:
        return minimum_players(self.settings.get("impostor_count", 2))


class RoomMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="memberships")
    player = models.ForeignKey(
        Player, on_delete=models.CASCADE, related_name="memberships"
    )
    color = models.PositiveSmallIntegerField(null=True, blank=True)
    is_connected = models.BooleanField(default=False)
    is_ready = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["room", "player"], name="unique_room_membership"
            ),
            models.UniqueConstraint(fields=["room", "color"], name="unique_room_color"),
            models.CheckConstraint(
                condition=models.Q(color__isnull=True)
                | models.Q(color__lt=PLAYER_COLORS),
                name="valid_room_color",
            ),
        ]
