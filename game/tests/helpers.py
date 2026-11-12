from players.authentication import create_guest_token
from players.models import Player
from rooms.models import Room, RoomMembership

MEMORY_CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


def make_room(count=4, code="ABC234"):
    players = [Player.objects.create(nickname=f"Player{i}") for i in range(count)]
    room = Room.objects.create(code=code, host=players[0])
    RoomMembership.objects.bulk_create([RoomMembership(room=room, player=player) for player in players])
    return room, players


def authorize(client, player):
    client.credentials(HTTP_AUTHORIZATION="Guest " + create_guest_token(player))
