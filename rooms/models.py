import uuid
from django.db import models
from players.models import Player


class Room(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        PLAYING = "playing", "Playing"
        MEETING = "meeting", "Meeting"
        FINISHED = "finished", "Finished"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=6, unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    host = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="hosted_rooms")
    max_players = models.PositiveSmallIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def min_players(self) -> int:
        return 4


class RoomMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="memberships")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="memberships")
    is_connected = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["room", "player"], name="unique_room_membership"),
        ]
