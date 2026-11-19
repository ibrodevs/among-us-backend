from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from game.models import GameSession
from game.tests.helpers import authorize, make_room
from players.models import Player
from rooms.models import RoomMembership


class ReadinessTests(TestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.room.memberships.update(is_ready=False)
        self.client = APIClient()
        self.url = f"/api/v1/rooms/{self.room.code}/ready/"
        self.start_url = f"/api/v1/games/{self.room.code}/start/"
        authorize(self.client, self.players[0])

    def ready(self, player, value=True):
        authorize(self.client, player)
        return self.client.patch(self.url, {"is_ready": value}, format="json")

    def test_default_false_and_only_own_readiness_can_change(self):
        self.assertFalse(self.room.memberships.filter(is_ready=True).exists())
        response = self.client.patch(
            self.url,
            {"is_ready": True, "player_id": str(self.players[1].pk)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["is_ready"] for p in response.json()["players"]], [True, False, False, False])
        self.assertEqual(self.ready(self.players[0]).status_code, 200)
        self.assertEqual(self.ready(self.players[0], False).status_code, 200)
        self.assertFalse(self.room.memberships.filter(is_ready=True).exists())

    def test_auth_membership_and_strict_boolean_validation(self):
        self.assertEqual(APIClient().patch(self.url, {"is_ready": True}, format="json").status_code, 401)
        outsider = Player.objects.create(nickname="Outsider")
        self.assertEqual(self.ready(outsider).status_code, 403)
        authorize(self.client, self.players[0])
        for body in ({}, {"is_ready": "false"}, {"is_ready": 1}, {"is_ready": None}, []):
            self.assertEqual(self.client.patch(self.url, body, format="json").status_code, 400)

    def test_start_requires_everyone_and_readiness_locks_after_start(self):
        self.assertEqual(self.client.post(self.start_url).status_code, 409)
        for player in self.players[:-1]:
            self.assertEqual(self.ready(player).status_code, 200)
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.start_url).status_code, 409)
        self.assertFalse(GameSession.objects.filter(room=self.room).exists())
        self.ready(self.players[-1])
        authorize(self.client, self.players[0])
        with patch("game.services.start.publish_start"):
            self.assertEqual(self.client.post(self.start_url).status_code, 200)
        self.assertEqual(self.ready(self.players[0], False).status_code, 409)

    def test_settings_change_resets_readiness_but_no_op_preserves_it(self):
        self.room.memberships.update(is_ready=True)
        url = f"/api/v1/rooms/{self.room.code}/settings/"
        self.assertEqual(self.client.patch(url, {}, format="json").status_code, 200)
        self.assertEqual(self.room.memberships.filter(is_ready=True).count(), 4)
        self.assertEqual(self.client.patch(url, {"impostor_count": 2}, format="json").status_code, 200)
        self.assertFalse(self.room.memberships.filter(is_ready=True).exists())

    def test_new_member_is_unready_and_blocks_start(self):
        self.room.memberships.update(is_ready=True)
        newcomer = Player.objects.create(nickname="Newcomer")
        authorize(self.client, newcomer)
        response = self.client.post("/api/v1/rooms/join/", {"code": self.room.code}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RoomMembership.objects.get(room=self.room, player=newcomer).is_ready)
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.start_url).status_code, 409)

    def test_readiness_notifies_lobby_after_commit(self):
        with patch("rooms.services.lobby_changed.send_robust") as notify:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.ready(self.players[0]).status_code, 200)
            notify.assert_called_once()
