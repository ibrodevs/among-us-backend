from unittest.mock import patch
from django.test import TestCase
from game import metrics


class ReadinessTests(TestCase):
    def test_ready_checks_both_dependencies(self):
        with patch("redis.Redis.from_url") as redis_client:
            redis_client.return_value.__enter__.return_value.ping.return_value = True
            response = self.client.get("/api/v1/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["checks"], {"database": True, "redis": True})

    def test_redis_failure_returns_503_without_exception_details(self):
        with patch("redis.Redis.from_url", side_effect=OSError("private endpoint")):
            response = self.client.get("/api/v1/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["checks"], {"database": True, "redis": False})
        self.assertNotIn("private endpoint", response.content.decode())

    def test_optional_telemetry_disk_failure_cannot_break_gameplay(self):
        with patch.object(metrics, "_ENABLED", True), patch.object(
            metrics, "_WRITTEN", 0
        ), patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            metrics.flush("api")
