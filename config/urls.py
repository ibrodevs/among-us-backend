from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", health),
    path("api/v1/guests/", include("players.urls")),
    path("api/v1/rooms/", include("rooms.urls")),
    path("api/v1/games/", include("game.urls")),
]
