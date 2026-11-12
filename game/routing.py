from django.urls import re_path
from game.consumers import RoomConsumer

websocket_urlpatterns = [
    re_path(r"^ws/rooms/(?P<code>[A-Z0-9]{6})/$", RoomConsumer.as_asgi()),
]
