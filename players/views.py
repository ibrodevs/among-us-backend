from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from players.authentication import create_guest_token
from players.models import Player
from players.serializers import GuestCreateSerializer


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def create_guest(request):
    serializer = GuestCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    player = Player.objects.create(nickname=serializer.validated_data["nickname"])
    return Response({
        "player_id": str(player.pk),
        "nickname": player.nickname,
        "token": create_guest_token(player),
    }, status=status.HTTP_201_CREATED)
