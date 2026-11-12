from django.test import TestCase
from rest_framework.test import APIClient


class RoomApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def guest(self, nickname):
        response = self.client.post("/api/v1/guests/", {"nickname": nickname}, format="json")
        self.assertEqual(response.status_code, 201)
        return response.json()

    def authorize(self, token):
        self.client.credentials(HTTP_AUTHORIZATION="Guest " + token)

    def test_guest_create_room_join_leave(self):
        host = self.guest("Ibro")
        self.authorize(host["token"])
        room_response = self.client.post("/api/v1/rooms/", {"max_players": 5}, format="json")
        self.assertEqual(room_response.status_code, 201)
        room = room_response.json()
        self.assertEqual(room["status"], "waiting")
        self.assertEqual(len(room["code"]), 6)
        member = self.guest("Bayel")
        self.authorize(member["token"])
        join = self.client.post("/api/v1/rooms/join/", {"code": room["code"]}, format="json")
        self.assertEqual(join.status_code, 200)
        self.assertEqual(len(join.json()["players"]), 2)
        self.assertEqual(self.client.post("/api/v1/rooms/" + room["code"] + "/leave/").status_code, 204)

    def test_guest_auth_required(self):
        self.assertEqual(self.client.post("/api/v1/rooms/", {}, format="json").status_code, 401)

    def test_health(self):
        self.assertEqual(self.client.get("/api/v1/health/").json()["status"], "ok")
