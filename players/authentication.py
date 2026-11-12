from django.core import signing
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from players.models import Player

TOKEN_SALT = "crew-mission-guest-v1"
TOKEN_MAX_AGE_SECONDS = 86400


class GuestPrincipal:
    def __init__(self, player: Player) -> None:
        self.player = player
        self.id = player.pk
        self.pk = player.pk
        self.is_authenticated = True


def create_guest_token(player: Player) -> str:
    return signing.dumps({"player_id": str(player.pk)}, salt=TOKEN_SALT, compress=True)


def validate_guest_token(token: str) -> Player:
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE_SECONDS)
        return Player.objects.get(pk=data["player_id"])
    except (signing.BadSignature, signing.SignatureExpired, Player.DoesNotExist, KeyError, ValueError, TypeError):
        raise AuthenticationFailed("Invalid or expired guest token")


class GuestAuthentication(BaseAuthentication):
    def authenticate(self, request):
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "guest" or not token:
            raise AuthenticationFailed("Expected Authorization: Guest <token>")
        return GuestPrincipal(validate_guest_token(token)), token

    def authenticate_header(self, request):
        return "Guest"
