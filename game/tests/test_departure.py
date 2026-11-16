from django.test import TestCase, override_settings
from unittest.mock import patch
from rest_framework.test import APIClient
from game.models import GameSession, PlayerGameState
from game.services.start import start_game
from game.tests.helpers import make_room, authorize, MEMORY_CHANNEL_LAYERS


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
class DepartureTests(TestCase):
    def test_leaving_impostor_finishes_match_and_preserves_history(self):
        room, players = make_room()
        with patch(
            "game.services.start.assign_roles",
            return_value={
                p.pk: "impostor" if i == 0 else "crew" for i, p in enumerate(players)
            },
        ):
            start_game(code=room.code, player=players[0])
        client = APIClient()
        authorize(client, players[0])
        response = client.post(f"/api/v1/rooms/{room.code}/leave/")
        self.assertEqual(response.status_code, 204)
        game = GameSession.objects.get(room=room)
        self.assertEqual(game.winner, "crew")
        self.assertFalse(PlayerGameState.objects.get(player=players[0]).alive)
        self.assertEqual(game.player_states.count(), 4)
        room.refresh_from_db()
        self.assertEqual(room.host_id, players[1].pk)
