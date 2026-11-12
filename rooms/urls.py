from django.urls import path
from rooms import views

urlpatterns = [
    path("", views.create_room, name="room-create"),
    path("join/", views.join_room, name="room-join"),
    path("<str:code>/", views.room_detail, name="room-detail"),
    path("<str:code>/leave/", views.leave_room, name="room-leave"),
]
