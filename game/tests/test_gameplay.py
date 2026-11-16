import math
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from django.db import close_old_connections, connection
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone
from game.models import (
    Corpse,
    GameSession,
    Meeting,
    PlayerGameState,
    TaskAssignment,
    Vote,
)
from game.physics import MAP, blocked, move
from game.services.simulation import (
    command,
    tick,
    public_snapshot,
    private_snapshot,
    RuleError,
    evaluate_win,
)
from game.services.start import start_game
from game.tests.helpers import make_room, MEMORY_CHANNEL_LAYERS


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
class GameplayTests(TestCase):
    def setUp(self):
        self.room, self.players = make_room()
        roles = {
            p.pk: "impostor" if i == 0 else "crew" for i, p in enumerate(self.players)
        }
        with patch("game.services.start.assign_roles", return_value=roles):
            start_game(code=self.room.code, player=self.players[0])
        self.game = GameSession.objects.get(room=self.room)
        self.now = timezone.now() + timedelta(seconds=26)
        self.game.last_tick_at = self.now
        self.game.save()
        for i, p in enumerate(self.players):
            PlayerGameState.objects.filter(game=self.game, player=p).update(
                x=760 + i * 20, y=450
            )

    def call(self, index, kind, **kwargs):
        return command(
            self.room.code, self.players[index].pk, {"type": kind, **kwargs}, self.now
        )

    def denied(self, code, index, kind, **kwargs):
        with self.assertRaises(RuleError) as caught:
            self.call(index, kind, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_shared_map_spawns_and_physics(self):
        self.assertTrue(all(not blocked(p["x"], p["y"]) for p in MAP["spawns"]))
        x, y = move(800, 450, 1, 1, 0.1)
        self.assertAlmostEqual(math.hypot(x - 800, y - 450), 15)
        x, y = move(434, 294, -1, 0, 2)
        self.assertGreaterEqual(x, 348)
        self.assertFalse(blocked(x, y))

    def test_move_server_speed_stale_sequences_and_invalid_numbers(self):
        self.call(1, "player.move", seq=1, direction={"x": 1, "y": 1}, x=99999, y=99999)
        tick(self.room.code, self.now + timedelta(seconds=0.1))
        state = self.game.player_states.get(player=self.players[1])
        self.assertAlmostEqual(math.hypot(state.x - 780, state.y - 450), 15, places=4)
        self.denied("STALE_SEQ", 1, "player.move", seq=1, direction={"x": 1, "y": 0})
        self.denied("RATE_LIMITED", 1, "player.move", seq=2, direction={"x": 1, "y": 0})
        for value in [float("nan"), float("inf"), True, 2, "1", 10**400]:
            self.denied(
                "BAD_PAYLOAD", 2, "player.move", seq=2, direction={"x": value, "y": 0}
            )

    def test_input_expires_and_duplicate_tick_does_not_double_move(self):
        self.call(1, "player.move", seq=1, direction={"x": 1, "y": 0})
        tick(self.room.code, self.now + timedelta(seconds=0.1))
        tick(self.room.code, self.now + timedelta(seconds=0.1))
        tick(self.room.code, self.now + timedelta(seconds=5))
        state = self.game.player_states.get(player=self.players[1])
        self.assertAlmostEqual(state.x, 795)

    def test_kill_permissions_distance_cooldown_and_duplicate(self):
        self.denied(
            "FORBIDDEN", 1, "player.kill", target_player_id=str(self.players[2].pk)
        )
        self.denied(
            "FORBIDDEN", 0, "player.kill", target_player_id=str(self.players[0].pk)
        )
        self.game.player_states.filter(player=self.players[1]).update(x=1200)
        self.denied(
            "OUT_OF_RANGE", 0, "player.kill", target_player_id=str(self.players[1].pk)
        )
        self.game.player_states.filter(player=self.players[1]).update(x=780)
        self.game.player_states.filter(player=self.players[0]).update(
            kill_available_at=self.now + timedelta(seconds=1)
        )
        self.denied(
            "COOLDOWN", 0, "player.kill", target_player_id=str(self.players[1].pk)
        )
        self.game.player_states.filter(player=self.players[0]).update(
            kill_available_at=self.now
        )
        events, public, own = self.call(
            0, "player.kill", target_player_id=str(self.players[1].pk)
        )
        self.assertEqual(Corpse.objects.count(), 1)
        self.assertFalse(
            public["players"][1]["alive"]
            if public["players"][1]["id"] == str(self.players[1].pk)
            else self.game.player_states.get(player=self.players[1]).alive
        )
        self.assertNotIn("role", str(events))
        self.assertEqual(own["role"], "impostor")
        self.denied(
            "FORBIDDEN", 0, "player.kill", target_player_id=str(self.players[1].pk)
        )
        self.denied(
            "COOLDOWN", 0, "player.kill", target_player_id=str(self.players[2].pk)
        )

    def test_dead_players_cannot_act_and_secret_roles_stay_private(self):
        self.call(0, "player.kill", target_player_id=str(self.players[1].pk))
        for kind in [
            "meeting.call",
            "player.move",
            "task.begin",
            "body.report",
            "vote.cast",
            "player.kill",
        ]:
            self.denied("FORBIDDEN", 1, kind)
        public = public_snapshot(self.game)
        self.assertNotIn("role", str(public))
        self.assertNotIn("challenge", str(public))
        self.assertEqual(
            len(private_snapshot(self.game, self.players[2].pk)["tasks"]), 3
        )
        self.assertEqual(
            len(private_snapshot(self.game, self.players[0].pk)["tasks"]), 0
        )

    def test_task_begin_location_time_solution_and_once(self):
        task = self.game.tasks.filter(player=self.players[1], task_type="wires").get()
        self.denied("OUT_OF_RANGE", 1, "task.begin", task_id=str(task.pk))
        config = next(t for t in MAP["tasks"] if t["point"] == task.task_point)
        self.game.player_states.filter(player=self.players[1]).update(
            x=config["x"], y=config["y"]
        )
        self.denied("FORBIDDEN", 2, "task.begin", task_id=str(task.pk))
        self.denied("FORBIDDEN", 0, "task.begin", task_id=str(task.pk))
        self.call(1, "task.begin", task_id=str(task.pk))
        task.refresh_from_db()
        self.denied(
            "TOO_EARLY",
            1,
            "task.complete",
            task_id=str(task.pk),
            solution=task.challenge,
        )
        self.now += timedelta(seconds=4)
        self.denied(
            "BAD_SOLUTION", 1, "task.complete", task_id=str(task.pk), solution=[9]
        )
        self.call(1, "task.complete", task_id=str(task.pk), solution=task.challenge)
        self.denied(
            "ALREADY_DONE",
            1,
            "task.complete",
            task_id=str(task.pk),
            solution=task.challenge,
        )

    def test_upload_requires_server_duration_and_still_near_terminal(self):
        task = self.game.tasks.get(player=self.players[1], task_type="upload")
        self.game.player_states.filter(player=self.players[1]).update(x=1067, y=294)
        self.call(1, "task.begin", task_id=str(task.pk))
        self.now += timedelta(seconds=7)
        self.denied("TOO_EARLY", 1, "task.complete", task_id=str(task.pk), solution=[])
        self.now += timedelta(seconds=2)
        self.game.player_states.filter(player=self.players[1]).update(x=800, y=450)
        self.denied(
            "OUT_OF_RANGE", 1, "task.complete", task_id=str(task.pk), solution=[]
        )
        self.game.player_states.filter(player=self.players[1]).update(x=1067, y=294)
        self.call(1, "task.complete", task_id=str(task.pk), solution=[])

    def test_report_begins_meeting_and_freezes_actions(self):
        self.call(0, "player.kill", target_player_id=str(self.players[1].pk))
        body = Corpse.objects.get()
        self.game.player_states.filter(player=self.players[2]).update(x=1200)
        self.denied("OUT_OF_RANGE", 2, "body.report", body_id=str(body.pk))
        self.game.player_states.filter(player=self.players[2]).update(x=800)
        self.call(2, "body.report", body_id=str(body.pk))
        for kind in [
            "player.move",
            "player.kill",
            "task.begin",
            "body.report",
            "meeting.call",
        ]:
            self.denied("INVALID_PHASE", 0, kind)
        self.assertEqual(Meeting.objects.count(), 1)

    def test_emergency_range_once_and_server_timers(self):
        self.game.player_states.filter(player=self.players[1]).update(x=1200)
        self.denied("OUT_OF_RANGE", 1, "meeting.call")
        self.game.player_states.filter(player=self.players[1]).update(x=800)
        self.call(1, "meeting.call")
        self.denied("INVALID_PHASE", 1, "vote.cast", target_player_id=None)
        tick(self.room.code, self.now + timedelta(seconds=61))
        self.game.refresh_from_db()
        self.assertEqual(
            public_snapshot(self.game, self.now + timedelta(seconds=61))["meeting"][
                "stage"
            ],
            "result",
        )
        tick(self.room.code, self.now + timedelta(seconds=67))
        self.game.refresh_from_db()
        self.assertEqual(self.game.phase, "playing")
        self.now += timedelta(seconds=68)
        self.denied("ALREADY_DONE", 1, "meeting.call")

    def vote(self, targets):
        self.call(1, "meeting.call")
        self.now += timedelta(seconds=31)
        for i, target in enumerate(targets):
            self.call(
                i,
                "vote.cast",
                target_player_id=(
                    str(self.players[target].pk) if target is not None else None
                ),
            )
        self.game.refresh_from_db()
        return self.game.meetings.get().result

    def test_skip_tie_and_one_vote_only(self):
        result = self.vote([0, 0, None, None])
        self.assertIsNone(result["ejected_player_id"])
        self.denied("INVALID_PHASE", 0, "vote.cast", target_player_id=None)

    def test_tied_candidates_no_ejection(self):
        self.assertIsNone(self.vote([0, 0, 1, 1])["ejected_player_id"])

    def test_majority_ejects_impostor_and_crew_wins(self):
        result = self.vote([None, 0, 0, 0])
        self.assertEqual(result["ejected_player_id"], str(self.players[0].pk))
        self.assertEqual(self.game.winner, "crew")
        self.assertEqual(self.game.finish_reason, "impostors_eliminated")
        self.denied("INVALID_PHASE", 1, "meeting.call")
        self.assertEqual(
            len(public_snapshot(self.game)["result"]["players_with_roles"]), 4
        )

    def test_repeat_vote_and_invalid_target(self):
        self.call(1, "meeting.call")
        self.now += timedelta(seconds=31)
        self.denied("BAD_PAYLOAD", 1, "vote.cast")
        self.denied("BAD_PAYLOAD", 1, "vote.cast", target_player_id="bad")
        self.call(1, "vote.cast", target_player_id=None)
        self.denied(
            "ALREADY_DONE", 1, "vote.cast", target_player_id=str(self.players[0].pk)
        )

    def test_parity_after_second_kill(self):
        self.call(0, "player.kill", target_player_id=str(self.players[1].pk))
        self.now += timedelta(seconds=26)
        self.call(0, "player.kill", target_player_id=str(self.players[2].pk))
        self.game.refresh_from_db()
        self.assertEqual(self.game.winner, "impostor")

    def test_last_required_task_wins_and_dead_obligations_retire(self):
        self.game.tasks.update(is_completed=True)
        last = self.game.tasks.filter(player=self.players[1], task_type="upload").get()
        last.is_completed = False
        last.save()
        self.game.player_states.filter(player=self.players[1]).update(x=1067, y=294)
        self.call(1, "task.begin", task_id=str(last.pk))
        self.now += timedelta(seconds=9)
        self.call(1, "task.complete", task_id=str(last.pk), solution=[])
        self.game.refresh_from_db()
        self.assertEqual(self.game.winner, "crew")
        self.assertEqual(self.game.finish_reason, "tasks_completed")


@override_settings(CHANNEL_LAYERS=MEMORY_CHANNEL_LAYERS)
@skipUnlessDBFeature("has_select_for_update")
class GameplayRaceTests(TransactionTestCase):
    def test_two_kills_of_same_target_create_one_body(self):
        room, players = make_room(7)
        with patch(
            "game.services.start.assign_roles",
            return_value={
                p.pk: "impostor" if i < 2 else "crew" for i, p in enumerate(players)
            },
        ):
            start_game(code=room.code, player=players[0])
        game = GameSession.objects.get(room=room)
        game.player_states.update(
            x=800, y=450, kill_available_at=timezone.now() - timedelta(seconds=1)
        )
        barrier = Barrier(2)

        def kill(i):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                command(
                    room.code,
                    players[i].pk,
                    {"type": "player.kill", "target_player_id": str(players[2].pk)},
                )
                return "ok"
            except RuleError as e:
                return e.code
            finally:
                connection.close()

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(kill, [0, 1]))
        self.assertEqual(sorted(results), ["FORBIDDEN", "ok"])
        self.assertEqual(Corpse.objects.count(), 1)
