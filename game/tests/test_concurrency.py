from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from rest_framework.test import APIClient

from game.models import GameSession, PlayerGameState
from game.services.roles import assign_roles
from game.tests.helpers import MEMORY_CHANNEL_LAYERS, authorize, make_room
from players.models import Player
from rooms.models import Room


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
@skipUnlessDBFeature("has_select_for_update")
class StartConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.url = f"/api/v1/games/{self.room.code}/start/"

    def request_in_thread(self, player, url, data=None, barrier=None):
        close_old_connections()
        try:
            client = APIClient()
            authorize(client, player)
            if barrier is not None:
                barrier.wait(timeout=10)
            return client.post(url, data=data or {}, format="json").status_code
        finally:
            connection.close()

    def test_two_parallel_starts_create_one_match(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.request_in_thread, self.players[0], self.url, barrier=barrier) for _ in range(2)]
            statuses = [f.result(timeout=15) for f in futures]
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(GameSession.objects.count(), 1)
        self.assertEqual(PlayerGameState.objects.count(), 4)
        self.assertEqual(PlayerGameState.objects.filter(role="impostor").count(), 1)

    def race_membership_with_start(self, player, url, data=None):
        locked = Event()
        release = Event()

        def pause_with_room_locked(ids):
            locked.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Test did not release start lock")
            return assign_roles(ids)

        with patch("game.services.start.assign_roles", side_effect=pause_with_room_locked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                start = pool.submit(self.request_in_thread, self.players[0], self.url)
                try:
                    self.assertTrue(locked.wait(timeout=10))
                    member = pool.submit(self.request_in_thread, player, url, data)
                finally:
                    release.set()
                self.assertEqual(start.result(timeout=15), 200)
                self.assertEqual(member.result(timeout=15), 409)

    def test_join_cannot_be_ignored_during_start(self):
        outsider = Player.objects.create(nickname="LateJoin")
        self.race_membership_with_start(outsider, "/api/v1/rooms/join/", {"code": self.room.code})
        self.assertFalse(self.room.memberships.filter(player=outsider).exists())
        self.assertEqual(set(PlayerGameState.objects.values_list("player_id", flat=True)), {p.pk for p in self.players})

    def test_leave_cannot_remove_a_player_during_start(self):
        self.race_membership_with_start(self.players[1], f"/api/v1/rooms/{self.room.code}/leave/")
        self.assertEqual(self.room.memberships.count(), 4)
        self.assertEqual(PlayerGameState.objects.count(), 4)
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.PLAYING)
