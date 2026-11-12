import uuid
from django.db import models


class Player(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nickname = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.nickname
