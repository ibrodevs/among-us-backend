from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["POST"])
def start_game(request, code: str):
    # Owned by Iliyar. Implement host authorization, state transition and
    # private role delivery. This explicit 501 avoids pretending a game started.
    return Response({"detail": "Game engine not implemented yet"}, status=status.HTTP_501_NOT_IMPLEMENTED)
