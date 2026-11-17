from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


def ready(_request):
    from django.db import connection
    from django.conf import settings
    import redis

    checks = {"database": False, "redis": False}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"] = cursor.fetchone()[0] == 1
    except Exception:
        pass
    try:
        with redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
        ) as client:
            checks["redis"] = bool(client.ping())
    except Exception:
        pass
    return JsonResponse(
        {"status": "ok" if all(checks.values()) else "unavailable", "checks": checks},
        status=200 if all(checks.values()) else 503,
    )


urlpatterns = [
    path("api/v1/ready/", ready),
    path("admin/", admin.site.urls),
    path("api/v1/health/", health),
    path("api/v1/guests/", include("players.urls")),
    path("api/v1/rooms/", include("rooms.urls")),
    path("api/v1/games/", include("game.urls")),
]
