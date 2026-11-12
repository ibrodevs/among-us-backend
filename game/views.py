from django.db import DatabaseError
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from game.services.start import start_game as start_match
from players.authentication import GuestAuthentication


class GameServiceUnavailable(APIException):
    status_code = 503
    default_detail = "Game service temporarily unavailable"
    default_code = "service_unavailable"


class StartGuestAuthentication(GuestAuthentication):
    def authenticate(self, request):
        # Guest lookup happens before the view. Keep DB outages safe here too,
        # without changing the shared players authentication implementation.
        try:
            return super().authenticate(request)
        except DatabaseError:
            raise GameServiceUnavailable() from None


@api_view(["POST"])
@authentication_classes([StartGuestAuthentication])
def start_game(request, code: str):
    try:
        room_data = start_match(code=code, player=request.user.player)
    except DatabaseError:
        raise GameServiceUnavailable() from None
    return Response(room_data)
