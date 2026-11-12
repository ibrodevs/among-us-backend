from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from rooms.models import Room, RoomMembership
from rooms.serializers import RoomCreateSerializer, RoomJoinSerializer, RoomSerializer
from rooms.services import create_room_for_player


def get_members_room(code: str, player):
    room = get_object_or_404(Room, code=code.upper())
    if not RoomMembership.objects.filter(room=room, player=player).exists():
        raise PermissionDenied("You are not a member of this room")
    return room


@api_view(["POST"])
def create_room(request):
    serializer = RoomCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    room = create_room_for_player(request.user.player, max_players=serializer.validated_data["max_players"])
    return Response(RoomSerializer(room).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def join_room(request):
    serializer = RoomJoinSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    player = request.user.player
    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), code=serializer.validated_data["code"])
        if RoomMembership.objects.filter(room=room, player=player).exists():
            return Response(RoomSerializer(room).data)
        if room.status != Room.Status.WAITING:
            return Response({"detail": "Room already started"}, status=status.HTTP_409_CONFLICT)
        if room.memberships.count() >= room.max_players:
            return Response({"detail": "Room is full"}, status=status.HTTP_409_CONFLICT)
        if RoomMembership.objects.filter(room=room, player__nickname__iexact=player.nickname).exists():
            return Response({"detail": "Nickname already used in this room"}, status=status.HTTP_409_CONFLICT)
        RoomMembership.objects.create(room=room, player=player)
    return Response(RoomSerializer(room).data)


@api_view(["GET"])
def room_detail(request, code: str):
    return Response(RoomSerializer(get_members_room(code, request.user.player)).data)


@api_view(["POST"])
def leave_room(request, code: str):
    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), code=code.upper())
        membership = get_object_or_404(RoomMembership, room=room, player=request.user.player)
        if room.status != Room.Status.WAITING:
            return Response({"detail": "In-game leaving will be handled by the game engine"}, status=status.HTTP_409_CONFLICT)
        membership.delete()
        next_host = room.memberships.select_related("player").order_by("joined_at").first()
        if next_host is None:
            room.delete()
        elif room.host_id == request.user.player.id:
            room.host = next_host.player
            room.save(update_fields=["host"])
    return Response(status=status.HTTP_204_NO_CONTENT)
