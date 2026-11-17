from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.cache import cache
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from players.authentication import TOKEN_MAX_AGE_SECONDS, create_guest_token
from players.models import Player
from rooms.models import Room, RoomMembership
from rooms.signals import lobby_changed

GUESTS = "/api/v1/guests/"
ROOMS = "/api/v1/rooms/"
JOIN = ROOMS + "join/"


def authorized_client(player):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Guest " + create_guest_token(player))
    return client


class RoomApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.host = Player.objects.create(nickname="Ibro")
        self.client = authorized_client(self.host)

    def room(self, seats=10):
        response = self.client.post(
            ROOMS, {"max_players": seats, "impostor_count": 1}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def member(self, nickname):
        return authorized_client(Player.objects.create(nickname=nickname))

    def test_guest_validates_nickname_and_returns_signed_identity(self):
        for value in ("A", "a" * 17, "   ", 1234, "A\nB"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.client.post(
                        GUESTS, {"nickname": value}, format="json"
                    ).status_code,
                    400,
                )
        for value in ("Ай", "a" * 16):
            with self.subTest(value=value):
                response = self.client.post(
                    GUESTS, {"nickname": f" {value} "}, format="json"
                )
                self.assertEqual(response.status_code, 201)
                guest = response.json()
                self.assertEqual(guest["nickname"], value)
                self.assertTrue(
                    Player.objects.filter(
                        pk=guest["player_id"], nickname=value
                    ).exists()
                )
                self.client.credentials(HTTP_AUTHORIZATION="Guest " + guest["token"])
                self.assertEqual(
                    self.client.post(ROOMS, {}, format="json").status_code, 201
                )

    def test_guest_creation_rate_ignores_forged_forwarded_ip(self):
        for attempt in range(31):
            response = self.client.post(
                GUESTS,
                {"nickname": "Guest"},
                format="json",
                REMOTE_ADDR="192.0.2.1",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{attempt}",
            )
            self.assertEqual(response.status_code, 201 if attempt < 30 else 429)

    def test_missing_invalid_and_expired_tokens(self):
        old_time = 1_700_000_000
        with patch("django.core.signing.time.time", return_value=old_time):
            expired = create_guest_token(self.host)
        with patch(
            "django.core.signing.time.time",
            return_value=old_time + TOKEN_MAX_AGE_SECONDS + 1,
        ):
            for authorization in ("", "Guest bad-token", "Guest " + expired):
                with self.subTest(authorization=authorization[:14]):
                    response = APIClient().post(
                        ROOMS, {}, format="json", HTTP_AUTHORIZATION=authorization
                    )
                    self.assertEqual(response.status_code, 401)

    def test_host_creation_and_code_collision(self):
        path = "rooms.services.new_room_code"
        with patch(path, side_effect=("AB12CD", "AB12CD", "AB12CE")):
            first, second = self.room(), self.room()
        self.assertEqual((first["code"], second["code"]), ("AB12CD", "AB12CE"))
        self.assertEqual(first["status"], "waiting")
        self.assertEqual(first["min_players"], 4)
        self.assertEqual(first["host_player_id"], str(self.host.pk))
        self.assertEqual(
            first["players"],
            [
                {
                    "id": str(self.host.pk),
                    "nickname": "Ibro",
                    "is_host": True,
                    "is_connected": False,
                    "color": 0,
                }
            ],
        )

    def test_capacity_limits(self):
        for value in (3, 21):
            self.assertEqual(
                self.client.post(
                    ROOMS, {"max_players": value, "impostor_count": 1}, format="json"
                ).status_code,
                400,
            )
        for value in (4, 10, 20):
            self.assertEqual(self.room(value)["max_players"], value)
        self.assertEqual(
            self.client.post(ROOMS, {}, format="json").json()["max_players"], 20
        )

    def test_invalid_and_missing_room_codes(self):
        for code in ("AB12C", "ab12cd", "AB!2CD", "AB12CĐ"):
            self.assertEqual(
                self.client.post(JOIN, {"code": code}, format="json").status_code, 400
            )
        self.assertEqual(
            self.client.post(JOIN, {"code": "AB12CD"}, format="json").status_code, 404
        )

    def test_duplicate_join_and_nickname(self):
        room = self.room()
        member = self.member("Байэл")
        for _ in range(2):
            response = member.post(JOIN, {"code": room["code"]}, format="json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["players"]), 2)
        self.assertEqual(
            self.member("байэл")
            .post(JOIN, {"code": room["code"]}, format="json")
            .status_code,
            409,
        )

    def test_full_and_started_rooms_reject_new_members(self):
        room = self.room(4)
        for name in ("Bayel", "Islam", "Iliyar"):
            self.assertEqual(
                self.member(name)
                .post(JOIN, {"code": room["code"]}, format="json")
                .status_code,
                200,
            )
        guest = self.member("Meder")
        self.assertEqual(
            guest.post(JOIN, {"code": room["code"]}, format="json").status_code, 409
        )
        Room.objects.filter(code=room["code"]).update(
            status=Room.Status.PLAYING, max_players=10
        )
        self.assertEqual(
            guest.post(JOIN, {"code": room["code"]}, format="json").status_code, 409
        )

    def test_room_detail_is_private_and_query_count_stays_constant(self):
        room = self.room()
        detail = f'{ROOMS}{room["code"]}/'
        stranger = self.member("Bayel")
        self.assertEqual(stranger.get(detail).status_code, 403)
        self.assertEqual(stranger.post(detail + "leave/").status_code, 404)
        self.assertEqual(self.client.get(ROOMS + "MISSING/").status_code, 404)
        for expected_size in (1, 2):
            with self.assertNumQueries(4):
                response = self.client.get(detail)
            self.assertEqual(response.status_code, 200)
            players = response.json()["players"]
            self.assertEqual(len(players), expected_size)
            for player in players:
                self.assertEqual(
                    set(player), {"id", "nickname", "is_host", "is_connected", "color"}
                )
            stranger.post(JOIN, {"code": room["code"]}, format="json")

    def test_host_transfer_empty_lobby_and_commit_notifications(self):
        room = self.room()
        code = room["code"]
        detail = f"{ROOMS}{code}/"
        next_host = self.member("Bayel")
        later_member = self.member("Iliyar")
        with patch.object(lobby_changed, "send_robust") as send:
            with self.captureOnCommitCallbacks(execute=True):
                next_host.post(JOIN, {"code": code}, format="json")
                next_host.post(JOIN, {"code": code}, format="json")
                later_member.post(JOIN, {"code": code}, format="json")
                self.assertEqual(self.client.post(detail + "leave/").status_code, 204)
                self.assertEqual(
                    next_host.get(detail).json()["players"][0]["nickname"], "Bayel"
                )
                self.assertTrue(next_host.get(detail).json()["players"][0]["is_host"])
                self.assertEqual(next_host.post(detail + "leave/").status_code, 204)
                self.assertEqual(later_member.post(detail + "leave/").status_code, 204)
                send.assert_not_called()
            self.assertEqual(send.call_count, 5)
            send.assert_called_with(sender=Room, room_code=code)
        self.assertFalse(Room.objects.filter(code=code).exists())

    def test_health(self):
        self.assertEqual(APIClient().get("/api/v1/health/").json(), {"status": "ok"})


class RoomConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_players_compete_for_the_last_seat(self):
        host = Player.objects.create(nickname="Host")
        room = Room.objects.create(code="ABC123", host=host, max_players=4)
        for player in (
            host,
            Player.objects.create(nickname="One"),
            Player.objects.create(nickname="Two"),
        ):
            RoomMembership.objects.create(room=room, player=player)
        contenders = [
            Player.objects.create(nickname=name) for name in ("Three", "Four")
        ]
        ready = Barrier(2, timeout=10)

        def join(player):
            close_old_connections()
            try:
                client = authorized_client(player)
                ready.wait()
                return client.post(JOIN, {"code": room.code}, format="json").status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(join, contenders))
        self.assertCountEqual(outcomes, [200, 409])
        self.assertEqual(room.memberships.count(), 4)
