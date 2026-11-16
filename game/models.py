"""Durable match state. Roles and assignments are private to their owner."""

import uuid

from django.db import models


class GameSession(models.Model):
    class Phase(models.TextChoices):
        PLAYING = "playing", "Playing"
        MEETING = "meeting", "Meeting"
        FINISHED = "finished", "Finished"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.OneToOneField("rooms.Room", on_delete=models.CASCADE, related_name="game")
    phase = models.CharField(max_length=10, choices=Phase.choices, default=Phase.PLAYING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    state_version = models.PositiveBigIntegerField(default=1)


class PlayerGameState(models.Model):
    class Role(models.TextChoices):
        CREW = "crew", "Crew"
        IMPOSTOR = "impostor", "Impostor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="player_states")
    player = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="game_states")
    role = models.CharField(max_length=8, choices=Role.choices)
    alive = models.BooleanField(default=True)
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    last_move_seq = models.PositiveBigIntegerField(default=0)
    last_move_at = models.DateTimeField(null=True, blank=True)
    kill_available_at = models.DateTimeField(null=True, blank=True)
    emergency_available_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "player"], name="unique_game_player"),
            models.CheckConstraint(condition=models.Q(role__in=["crew", "impostor"]), name="valid_game_role"),
        ]


class TaskAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="tasks")
    player = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="tasks")
    task_type = models.CharField(max_length=32)
    task_point = models.CharField(max_length=64)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "player", "task_point"], name="unique_player_task_point"),
        ]


# Schema for later stages only; stage A does not execute these actions.
class Corpse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="corpses")
    player = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="corpses")
    x = models.FloatField()
    y = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["game", "player"], name="unique_game_corpse")]


class Meeting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    game = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="meetings")
    number = models.PositiveIntegerField()
    reporter = models.ForeignKey("players.Player", on_delete=models.SET_NULL, null=True, blank=True)
    corpse = models.ForeignKey(Corpse, on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["game", "number"], name="unique_game_meeting")]


class Vote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="votes")
    voter = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="votes_cast")
    target = models.ForeignKey("players.Player", on_delete=models.CASCADE, null=True, blank=True, related_name="votes_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["meeting", "voter"], name="unique_meeting_vote")]
