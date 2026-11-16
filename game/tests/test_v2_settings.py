from django.test import TestCase
from rest_framework.test import APIClient
from game.tests.helpers import make_room, authorize
from game.services.start import start_game
from game.settings import validate_settings
from rest_framework.exceptions import ValidationError
from unittest.mock import patch


class SettingsAndAppearanceTests(TestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.client = APIClient()
        authorize(self.client, self.players[0])
        self.settings = f"/api/v1/rooms/{self.room.code}/settings/"
        self.appearance = f"/api/v1/rooms/{self.room.code}/appearance/"

    def test_settings_validation_authority_and_freeze(self):
        self.assertEqual(
            self.client.patch(
                self.settings,
                {
                    "map_version": 2,
                    "common_tasks": 1,
                    "short_tasks": 4,
                    "long_tasks": 2,
                },
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(self.settings, [], format="json").status_code, 400
        )
        for data in [
            {"speed": 999},
            {"special_roles": "true"},
            {"short_tasks": 7, "long_tasks": 3},
            {"role": "impostor"},
        ]:
            self.assertEqual(
                self.client.patch(self.settings, data, format="json").status_code, 400
            )
        authorize(self.client, self.players[1])
        self.assertEqual(
            self.client.patch(self.settings, {"speed": 210}, format="json").status_code,
            403,
        )
        self.assertEqual(self.client.get(self.settings).status_code, 200)
        with patch("game.services.start.publish_start"):
            start_game(code=self.room.code, player=self.players[0])
        authorize(self.client, self.players[0])
        self.assertEqual(
            self.client.patch(self.settings, {"speed": 210}, format="json").status_code,
            409,
        )
        self.assertEqual(self.room.game.settings["speed"], 220)

    def test_color_choice_is_unique_and_preserved(self):
        self.assertEqual(
            self.client.patch(self.appearance, {"color": 7}, format="json").status_code,
            200,
        )
        authorize(self.client, self.players[1])
        self.assertEqual(
            self.client.patch(self.appearance, {"color": 7}, format="json").status_code,
            409,
        )
        self.assertEqual(
            self.client.patch(
                self.appearance, {"color": True}, format="json"
            ).status_code,
            400,
        )
        self.room.settings = {"map_version": 2}
        self.room.save()
        with patch("game.services.start.publish_start"):
            start_game(code=self.room.code, player=self.players[0])
        states = list(self.room.game.player_states.all())
        self.assertEqual(len({s.color for s in states}), 4)
        self.assertEqual(
            next(s for s in states if s.player_id == self.players[0].pk).color, 7
        )
        self.assertEqual(
            self.client.patch(self.appearance, {"color": 2}, format="json").status_code,
            409,
        )
