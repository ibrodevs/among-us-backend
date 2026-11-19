from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.db import close_old_connections, transaction, IntegrityError
from django.utils import timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from rest_framework.test import APIClient
from game.tests.helpers import make_room, authorize
from game.services.start import start_game
from game.services.roles import spawn_points, assign_roles
from game.services.simulation import command, tick, private_snapshot, public_snapshot
from game.maps import game_map
from game.physics import blocked
from game.limits import minimum_players
from players.models import Player
from rooms.models import Room, RoomMembership


class TwentyPlayerTests(TestCase):
    def setUp(self):
        self.room, self.players = make_room(20)
        self.room.settings = {
            "map_version": 2,
            "impostor_count": 3,
            "discussion_seconds": 5,
            "voting_seconds": 5,
        }
        self.room.save()

    def start(self):
        with patch("game.services.start.publish_start"):
            start_game(code=self.room.code, player=self.players[0])
        return self.room.game

    def test_twenty_states_unique_colors_spawns_private_tasks(self):
        for i, m in enumerate(self.room.memberships.order_by("player_id")):
            m.color = i
            m.save()
        game = self.start()
        states = list(game.player_states.all())
        self.assertEqual(len(states), 20)
        self.assertEqual(game.map_mode, "full")
        self.assertEqual(sum(s.role == "impostor" for s in states), 3)
        self.assertEqual(len({s.color for s in states}), 20)
        self.assertEqual(len({(s.x, s.y) for s in states}), 20)
        for s in states:
            self.assertFalse(blocked(s.x, s.y, game_map(game)))
            own = private_snapshot(game, s.player_id)
            self.assertEqual(len(own["tasks"]), 7 if s.role == "crew" else 0)
            self.assertEqual(
                len(public_snapshot(game, viewer_id=s.player_id)["roster"]), 20
            )
        self.assertEqual(game.tasks.count(), 119)

    def test_short_movement_tap_settles_before_next_clock_tick(self):
        game = self.start()
        actor = game.player_states.first()
        now = timezone.now()
        game.last_tick_at = now
        game.save(update_fields=["last_tick_at"])
        direction = next(
            (dx, dy)
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
            if not blocked(actor.x + dx * 10, actor.y + dy * 10, game_map(game))
        )
        command(
            self.room.code,
            actor.player_id,
            {
                "type": "player.move",
                "seq": 1,
                "direction": {"x": direction[0], "y": direction[1]},
            },
            now=now,
        )
        _, snapshot, own = command(
            self.room.code,
            actor.player_id,
            {"type": "player.move", "seq": 2, "direction": {"x": 0, "y": 0}},
            now=now + timedelta(milliseconds=30),
        )
        distance = ((own["x"] - actor.x) ** 2 + (own["y"] - actor.y) ** 2) ** 0.5
        self.assertGreater(distance, 1)
        self.assertLessEqual(distance, 7)
        self.assertIsNone(snapshot)
        tick(self.room.code, now=now + timedelta(milliseconds=150))
        actor.refresh_from_db()
        self.assertAlmostEqual(actor.x, own["x"])
        self.assertAlmostEqual(actor.y, own["y"])

    def test_twenty_votes_and_resume_have_no_spawn_index_error(self):
        game = self.start()
        now = timezone.now()
        crew = game.player_states.filter(role="crew").first()
        p = game_map(game)["emergency"]
        crew.x, crew.y = p["x"], p["y"]
        crew.save()
        command(self.room.code, crew.player_id, {"type": "meeting.call"}, now=now)
        for state in game.player_states.all():
            command(
                self.room.code,
                state.player_id,
                {"type": "vote.cast", "target_player_id": None},
                now=now + timedelta(seconds=5.1),
            )
        meeting = game.meetings.get()
        self.assertEqual(meeting.votes.count(), 20)
        self.assertIsNone(meeting.result["ejected_player_id"])
        tick(self.room.code, now=now + timedelta(seconds=11))
        game.refresh_from_db()
        self.assertEqual(game.phase, "playing")
        self.assertEqual(len(set(game.player_states.values_list("x", "y"))), 20)

    def test_twenty_on_legacy_and_after_meeting(self):
        self.room.settings = {"map_version": 1}
        self.room.save()
        game = self.start()
        points = spawn_points(game)
        self.assertEqual(game.player_states.count(), 20)
        self.assertEqual(len(points), 20)
        self.assertTrue(
            all(not blocked(p["x"], p["y"], game_map(game)) for p in points)
        )
        now = timezone.now()
        crew = game.player_states.filter(role="crew").first()
        p = game_map(game)["emergency"]
        crew.x, crew.y = p["x"], p["y"]
        crew.save()
        command(self.room.code, crew.player_id, {"type": "meeting.call"}, now=now)
        meeting = game.meetings.get()
        tick(self.room.code, now=meeting.voting_ends_at + timedelta(seconds=0.1))
        tick(self.room.code, now=meeting.voting_ends_at + timedelta(seconds=6))
        game.refresh_from_db()
        self.assertEqual(game.phase, "playing")
        self.assertEqual(len(set(game.player_states.values_list("x", "y"))), 20)

    def test_settings_and_color_limits_are_server_owned(self):
        client = APIClient()
        authorize(client, self.players[0])
        code = self.room.code
        self.assertEqual(
            client.patch(
                f"/api/v1/rooms/{code}/settings/", {"max_players": 19}, format="json"
            ).status_code,
            400,
        )
        for color, status in [(19, 200), (20, 400), (-1, 400)]:
            self.assertEqual(
                client.patch(
                    f"/api/v1/rooms/{code}/appearance/", {"color": color}, format="json"
                ).status_code,
                status,
            )
        authorize(client, self.players[1])
        self.assertEqual(
            client.patch(
                f"/api/v1/rooms/{code}/appearance/", {"color": 19}, format="json"
            ).status_code,
            409,
        )
        for chosen, required in [(1, 4), (2, 7), (3, 10)]:
            self.assertEqual(minimum_players(chosen), required)
            for size in [required, 20]:
                self.assertEqual(
                    list(assign_roles(list(range(size)), chosen).values()).count(
                        "impostor"
                    ),
                    chosen,
                )
            with self.assertRaises(ValueError):
                assign_roles(list(range(required - 1)), chosen)
        for chosen in [0, 4, True, "2"]:
            with self.assertRaises(ValueError):
                assign_roles(list(range(20)), chosen)

    def test_shared_frame_filters_twenty_observers_without_repeat_queries(self):
        from game.services.frames import observer_frame

        game = self.start()
        with patch("game.services.frames.time.monotonic", return_value=1):
            first = observer_frame(game, self.players[0].pk)
            with self.assertNumQueries(0):
                for p in self.players:
                    public, own = observer_frame(game, p.pk)
                    self.assertEqual(
                        own["role"],
                        game._frame["states"][
                            next(
                                i
                                for i, s in enumerate(game._frame["states"])
                                if s.player_id == p.pk
                            )
                        ].role,
                    )
                    self.assertTrue(all("role" not in s for s in public["players"]))
                    self.assertEqual(own["game_id"], str(game.pk))

    def test_database_rejects_invalid_capacity_and_color(self):
        for size in [3, 21]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Room.objects.filter(pk=self.room.pk).update(max_players=size)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.room.memberships.filter(player=self.players[0]).update(color=20)


class TwentySeatRaceTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_joiners_compete_for_twentieth_seat(self):
        room, players = make_room(19)
        contenders = [Player.objects.create(nickname=f"Joiner{i}") for i in range(2)]
        ready = Barrier(2, timeout=10)

        def join(p):
            close_old_connections()
            try:
                client = APIClient()
                authorize(client, p)
                ready.wait()
                return client.post(
                    "/api/v1/rooms/join/", {"code": room.code}, format="json"
                ).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(join, contenders))
        self.assertCountEqual(results, [200, 409])
        self.assertEqual(room.memberships.count(), 20)


class HostSelectedRolesTests(TestCase):
    def test_defaults_and_insufficient_roster_then_host_selection(self):
        room, players = make_room(4)
        room.settings = {}
        room.save()
        client = APIClient()
        authorize(client, players[0])
        url = f"/api/v1/rooms/{room.code}/settings/"
        self.assertEqual(client.get(url).json()["impostor_count"], 2)
        self.assertEqual(
            client.post(f"/api/v1/games/{room.code}/start/").status_code, 409
        )
        self.assertFalse(hasattr(room, "game"))
        self.assertEqual(
            client.patch(url, {"impostor_count": 1}, format="json").status_code, 200
        )
        room.memberships.update(is_ready=True)
        with patch("game.services.start.publish_start"):
            self.assertEqual(
                client.post(f"/api/v1/games/{room.code}/start/").status_code, 200
            )
        room.refresh_from_db()
        self.assertEqual(room.game.player_states.filter(role="impostor").count(), 1)
        self.assertEqual(
            client.patch(url, {"impostor_count": 3}, format="json").status_code, 409
        )

    def test_ordinary_member_invalid_count_and_impossible_capacity(self):
        room, players = make_room(4)
        client = APIClient()
        url = f"/api/v1/rooms/{room.code}/settings/"
        authorize(client, players[1])
        self.assertEqual(
            client.patch(url, {"impostor_count": 3}, format="json").status_code, 403
        )
        authorize(client, players[0])
        for count in [0, 4, True, "three"]:
            self.assertEqual(
                client.patch(url, {"impostor_count": count}, format="json").status_code,
                400,
            )
        self.assertEqual(
            client.patch(
                url, {"max_players": 4, "impostor_count": 2}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            client.patch(
                url, {"max_players": 4, "impostor_count": 1}, format="json"
            ).status_code,
            200,
        )

    def test_each_host_selected_count_is_exact_and_private(self):
        for chosen, size in [(1, 4), (2, 7), (3, 10), (3, 20)]:
            room, players = make_room(size, code=f"R{chosen}{size:04}")
            room.settings = {"map_version": 2, "impostor_count": chosen}
            room.save()
            with patch("game.services.start.publish_start"):
                start_game(code=room.code, player=players[0])
            self.assertEqual(room.game.player_states.count(), size)
            self.assertEqual(
                room.game.player_states.filter(role="impostor").count(), chosen
            )
            view = public_snapshot(room.game, viewer_id=players[0].pk)
            self.assertTrue(all("role" not in p for p in view["players"]))

    def test_worker_leader_session_lock_releases(self):
        from game.worker_leader import ClockLeader

        with patch("game.worker_leader.KEY", 1234567123):
            first, second = ClockLeader(), ClockLeader()
            try:
                self.assertTrue(first.acquire())
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                first.close()
                self.assertTrue(second.acquire())
                # Reopening a dead native session must reacquire the lock.
                second.conn.close()
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
            finally:
                first.close()
                second.close()
