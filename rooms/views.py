from unicodedata import normalize

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from rooms.models import Room, RoomMembership
from rooms.serializers import RoomCreateSerializer, RoomJoinSerializer, RoomSerializer
from rooms.services import create_room_for_player, notify_lobby_changed


def get_members_room(code: str, player):
    room = get_object_or_404(Room, code=code.upper())
    if not RoomMembership.objects.filter(room=room, player=player).exists():
        raise PermissionDenied("You are not a member of this room")
    return room


@api_view(["POST"])
def create_room(request):
    serializer = RoomCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    room = create_room_for_player(
        request.user.player, max_players=serializer.validated_data["max_players"]
    )
    return Response(RoomSerializer(room).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def join_room(request):
    serializer = RoomJoinSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    player = request.user.player
    with transaction.atomic():
        room = get_object_or_404(
            Room.objects.select_for_update(), code=serializer.validated_data["code"]
        )
        if RoomMembership.objects.filter(room=room, player=player).exists():
            return Response(RoomSerializer(room).data)
        if room.status != Room.Status.WAITING:
            return Response(
                {"detail": "Room already started"}, status=status.HTTP_409_CONFLICT
            )
        if room.memberships.count() >= room.max_players:
            return Response({"detail": "Room is full"}, status=status.HTTP_409_CONFLICT)
        nickname = normalize("NFC", player.nickname).casefold()
        member_names = room.memberships.values_list("player__nickname", flat=True)
        if any(normalize("NFC", name).casefold() == nickname for name in member_names):
            return Response(
                {"detail": "Nickname already used in this room"},
                status=status.HTTP_409_CONFLICT,
            )
        RoomMembership.objects.create(room=room, player=player)
        notify_lobby_changed(room.code)
        return Response(RoomSerializer(room).data)


@api_view(["GET"])
def room_detail(request, code: str):
    return Response(RoomSerializer(get_members_room(code, request.user.player)).data)


@api_view(["POST"])
def leave_room(request, code: str):
    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), code=code.upper())
        membership = get_object_or_404(
            RoomMembership, room=room, player=request.user.player
        )
        membership.delete()
        if room.status != Room.Status.WAITING:
            from game.services.departure import depart_match

            depart_match(room, request.user.player)
        next_host = (
            room.memberships.select_related("player")
            .order_by("joined_at", "id")
            .first()
        )
        if next_host is None:
            if room.status == Room.Status.WAITING:
                room.delete()
        elif room.host_id == request.user.player.id:
            room.host = next_host.player
            room.save(update_fields=["host"])
        notify_lobby_changed(room.code)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "PATCH"])
def room_settings(request, code):
    from game.settings import settings_for, validate_settings

    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), code=code.upper())
        if not RoomMembership.objects.filter(
            room=room, player=request.user.player
        ).exists():
            raise PermissionDenied("You are not a member")
        if request.method == "PATCH":
            if room.host_id != request.user.player.pk:
                raise PermissionDenied("Host only")
            if room.status != "waiting":
                return Response(
                    {"detail": "Settings are locked after start"}, status=409
                )
            if not isinstance(request.data, dict):
                raise ValidationError({"detail": "Expected a settings object"})
            room.settings = validate_settings({**settings_for(room), **request.data})
            if room.settings["max_players"] < room.memberships.count():
                raise ValidationError(
                    {"detail": "Maximum cannot be below the current roster"}
                )
            room.max_players = room.settings["max_players"]
            room.save(update_fields=["settings", "max_players"])
            notify_lobby_changed(room.code)
        return Response(settings_for(room))


@api_view(["GET", "PATCH"])
def room_appearance(request, code):
    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), code=code.upper())
        member = get_object_or_404(
            RoomMembership, room=room, player=request.user.player
        )
        if request.method == "PATCH":
            if room.status != "waiting":
                return Response(
                    {"detail": "Appearance is locked after start"}, status=409
                )
            color = (
                request.data.get("color") if isinstance(request.data, dict) else None
            )
            if type(color) is not int or not 0 <= color < 10:
                raise ValidationError({"detail": "Choose a color from 0 to 9"})
            if room.memberships.filter(color=color).exclude(pk=member.pk).exists():
                return Response(
                    {"detail": "This color is already selected"}, status=409
                )
            member.color = color
            member.save(update_fields=["color"])
            notify_lobby_changed(room.code)
        return Response(
            {
                "players": [
                    {"player_id": str(m.player_id), "color": m.color}
                    for m in room.memberships.all()
                ]
            }
        )
