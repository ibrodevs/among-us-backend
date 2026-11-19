from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rooms", "0004_remove_roommembership_valid_room_color_and_more")]
    operations = [
        migrations.AddField(
            model_name="roommembership",
            name="is_ready",
            field=models.BooleanField(default=False),
        ),
    ]
