from django.db import transaction
from django.utils import timezone
from game.models import GameSession
from game.services.simulation import evaluate_win, public_snapshot
from game.services.transport import publish_update


def depart_match(room, player):
    """Caller holds the Room lock. Preserve match roster and finished role history."""
    game = GameSession.objects.select_for_update().get(room=room)
    if game.phase != "finished":
        game.player_states.filter(player=player).update(
            alive=False, direction_x=0, direction_y=0
        )
        evaluate_win(game, room, timezone.now())
        game.state_version += 1
        game.save()
    snapshot = public_snapshot(game)
    events = (
        [{"type": "game.ended", **snapshot["result"]}]
        if game.phase == "finished"
        else []
    )
    transaction.on_commit(lambda: publish_update(room.code, snapshot, events, True))
