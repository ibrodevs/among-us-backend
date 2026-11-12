import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Player",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("nickname", models.CharField(max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
