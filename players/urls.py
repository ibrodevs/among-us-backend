from django.urls import path
from players.views import create_guest

urlpatterns = [path("", create_guest, name="create-guest")]
