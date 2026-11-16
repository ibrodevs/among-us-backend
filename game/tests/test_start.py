from unittest.mock import patch

from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from game.models import Corpse, GameSession, Meeting, PlayerGameState, TaskAssignment, Vote
from game.services.roles import SPAWN_POINTS, assign_roles
from game.services.start import start_game
from game.tests.helpers import MEMORY_CHANNEL_LAYERS, authorize, make_room
from players.models import Player
from rooms.models import Room, RoomMembership
from rooms.serializers import RoomSerializer


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
class StartApiTests(TestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.client = APIClient()
        self.url = f"/api/v1/games/{self.room.code}/start/"

    def assert_waiting(self):
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.WAITING)
        self.assertFalse(GameSession.objects.filter(room=self.room).exists())
        self.assertFalse(PlayerGameState.objects.exists())

    def test_missing_and_invalid_token(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Guest invalid")
        self.assertEqual(self.client.post(self.url).status_code, 401)
        self.assert_waiting()

    def test_unknown_room(self):
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post("/api/v1/games/ZZZ999/start/").status_code, 404)

    def test_database_failure_during_guest_lookup_is_safe(self):
        authorize(self.client, self.players[0])
        with patch("players.authentication.validate_guest_token", side_effect=DatabaseError("private database details")):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Game service temporarily unavailable"})
        self.assert_waiting()

    def test_non_member_and_non_host(self):
        outsider = Player.objects.create(nickname="Outsider")
        for player in (outsider, self.players[1]):
            with self.subTest(player=player.nickname):
                authorize(self.client, player)
                self.assertEqual(self.client.post(self.url).status_code, 403)
                self.assert_waiting()

    def test_host_must_also_be_member(self):
        RoomMembership.objects.filter(room=self.room, player=self.players[0]).delete()
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assert_waiting()

    def test_one_to_three_players(self):
        authorize(self.client, self.players[0])
        for count in (3, 2, 1):
            RoomMembership.objects.filter(room=self.room, player=self.players[count]).delete()
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json(), {"detail": "At least 4 players required"})
            self.assert_waiting()

    def test_all_valid_roster_sizes_roles_and_spawns(self):
        for count in range(4, 11):
            with self.subTest(count=count):
                room, players = make_room(count, code=f"TEST{count:02}")
                # Offline members are still part of the fixed match roster.
                self.assertFalse(room.memberships.filter(is_connected=True).exists())
                authorize(self.client, players[0])
                response = self.client.post(f"/api/v1/games/{room.code}/start/", {"role": "impostor", "roles": {}}, format="json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "playing")
                game = GameSession.objects.get(room=room)
                states = game.player_states.all()
                self.assertEqual(states.count(), count)
                self.assertEqual(states.filter(role="impostor").count(), 1 if count <= 6 else 2)
                self.assertEqual(states.filter(role="crew").count(), count - (1 if count <= 6 else 2))
                self.assertEqual(set(states.values_list("player_id", flat=True)), {p.pk for p in players})
                points = set(states.values_list("x", "y"))
                self.assertEqual(len(points), count)
                self.assertTrue(points.issubset(SPAWN_POINTS))
                self.assertTrue(all(0 < x < 1600 and 0 < y < 900 for x, y in points))
                self.assertEqual(states.filter(alive=True, last_move_seq=0).count(), count)
                self.assertEqual(game.phase, "playing")
                self.assertIsNone(game.finished_at)
                self.assertEqual(game.state_version, 1)
                self.assertFalse(game.tasks.exists())

    def test_over_capacity_rejected(self):
        for i in range(7):
            player = Player.objects.create(nickname=f"Extra{i}")
            RoomMembership.objects.create(room=self.room, player=player)
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assert_waiting()

    def test_configured_capacity_enforced(self):
        self.room.max_players = 3
        self.room.save(update_fields=["max_players"])
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assert_waiting()

    def test_repeat_start_preserves_roles(self):
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.url).status_code, 200)
        roles = list(PlayerGameState.objects.order_by("player_id").values_list("player_id", "role"))
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assertEqual(GameSession.objects.count(), 1)
        self.assertEqual(list(PlayerGameState.objects.order_by("player_id").values_list("player_id", "role")), roles)

    def test_existing_game_in_waiting_room_rejected(self):
        GameSession.objects.create(room=self.room)
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assertEqual(GameSession.objects.count(), 1)

    def test_non_waiting_statuses_rejected(self):
        authorize(self.client, self.players[0])
        for status in ("playing", "meeting", "finished"):
            self.room.status = status
            self.room.save(update_fields=["status"])
            self.assertEqual(self.client.post(self.url).status_code, 409)
        self.assertFalse(GameSession.objects.exists())

    def test_database_failure_rolls_back_game_states_and_room(self):
        authorize(self.client, self.players[0])
        # Fail after session and player states have been inserted.
        with patch("rooms.models.Room.save", side_effect=DatabaseError("private database details")):
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.client.post(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Game service temporarily unavailable"})
        self.assertEqual(callbacks, [])
        self.assert_waiting()

    def test_notifications_only_after_commit(self):
        with patch("game.services.start.publish_start") as publish:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                start_game(code=self.room.code, player=self.players[0])
                publish.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            publish.assert_called_once()
            payload, recipients = publish.call_args.args
            self.assertEqual(payload["status"], "playing")
            self.assertEqual(set(recipients), {p.pk for p in self.players})

    def test_redis_failure_keeps_committed_match_recoverable(self):
        authorize(self.client, self.players[0])
        with patch("game.services.events._publish_start", side_effect=RedisConnectionError("private redis details")):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GameSession.objects.count(), 1)
        self.assertEqual(PlayerGameState.objects.count(), 4)
        self.assertEqual(self.client.post(self.url).status_code, 409)

    def test_public_rest_and_serializer_allowlist(self):
        authorize(self.client, self.players[0])
        response = self.client.post(self.url)
        self.room.refresh_from_db()
        expected = {"id", "code", "status", "min_players", "max_players", "host_player_id", "players", "created_at"}
        for data in (response.json(), RoomSerializer(self.room).data, self.client.get(f"/api/v1/rooms/{self.room.code}/").json()):
            self.assertEqual(set(data), expected)
            for player in data["players"]:
                self.assertEqual(set(player), {"id", "nickname", "is_host", "is_connected"})

    def test_only_post_allowed(self):
        authorize(self.client, self.players[0])
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assert_waiting()

    def test_role_selection_uses_secure_server_sample(self):
        ids = [p.pk for p in self.players]
        with patch("game.services.roles.secrets.SystemRandom") as random:
            random.return_value.sample.return_value = [ids[2]]
            roles = assign_roles(ids)
        random.return_value.sample.assert_called_once_with(ids, 1)
        self.assertEqual(roles[ids[2]], "impostor")
        self.assertEqual(sum(role == "crew" for role in roles.values()), 3)


class ModelConstraintsTests(TestCase):
    def test_database_unique_constraints(self):
        room, players = make_room()
        game = GameSession.objects.create(room=room)
        meeting = Meeting.objects.create(game=game, number=1)
        entries = [
            (GameSession, {"room": room}),
            (PlayerGameState, {"game": game, "player": players[0], "role": "crew"}),
            (TaskAssignment, {"game": game, "player": players[0], "task_point": "console-1", "task_type": "wires"}),
            (Corpse, {"game": game, "player": players[0], "x": 800, "y": 450}),
            (Meeting, {"game": game, "number": 1}),
            (Vote, {"meeting": meeting, "voter": players[0]}),
        ]
        for model, values in entries:
            with self.subTest(model=model.__name__):
                model.objects.get_or_create(**values)
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.create(**values)

    def test_invalid_role_rejected_by_database(self):
        room, players = make_room()
        game = GameSession.objects.create(room=room)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlayerGameState.objects.create(game=game, player=players[0], role="admin")
