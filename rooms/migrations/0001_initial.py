import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("players", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Room",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(db_index=True, max_length=6, unique=True)),
                ("status", models.CharField(choices=[("waiting", "Waiting"), ("playing", "Playing"), ("meeting", "Meeting"), ("finished", "Finished")], default="waiting", max_length=10)),
                ("max_players", models.PositiveSmallIntegerField(default=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("host", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="hosted_rooms", to="players.player")),
            ],
        ),
        migrations.CreateModel(
            name="RoomMembership",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("is_connected", models.BooleanField(default=False)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="players.player")),
                ("room", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="rooms.room")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("room", "player"), name="unique_room_membership")],
            },
        ),
    ]
