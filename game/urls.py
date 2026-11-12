from django.urls import path
from game.views import start_game

urlpatterns = [path("<str:code>/start/", start_game, name="game-start")]
