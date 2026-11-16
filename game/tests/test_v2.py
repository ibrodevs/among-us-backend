from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from game.tests.helpers import make_room
from game.services.start import start_game
from game.services.simulation import (
    command,
    public_snapshot,
    private_snapshot,
    tick,
    RuleError,
)
from game.maps import game_map
from game.tasks import KINDS, challenge, valid_solution
from game.v2 import appearance_id


class AsterionTests(TestCase):
    def setUp(self):
        self.room, self.players = make_room()
        self.room.settings = {"map_version": 2}
        self.room.save()
        with patch("game.services.start.publish_start"):
            start_game(code=self.room.code, player=self.players[0])
        self.game = self.room.game
        self.crew = self.game.player_states.filter(role="crew").first()
        self.imp = self.game.player_states.get(role="impostor")
        self.now = timezone.now()

    def action(self, state, event_type, **data):
        return command(
            self.room.code, state.player_id, {"type": event_type, **data}, now=self.now
        )

    def test_version_and_assignments(self):
        self.assertEqual(self.game.map_version, 2)
        self.assertEqual(self.game.map_mode, "compact")
        for p in self.game.player_states.filter(role="crew"):
            self.assertEqual(self.game.tasks.filter(player_id=p.player_id).count(), 7)
        self.assertEqual(len(game_map(self.game)["tasks"]), 40)
        self.assertEqual(len(KINDS), 20)

    def test_hidden_players_and_unscoped_snapshot(self):
        self.imp.x, self.imp.y = 650, 1230
        self.imp.save()
        view = public_snapshot(self.game, viewer_id=self.crew.player_id)
        self.assertNotIn(
            appearance_id(self.game, self.imp), [p["id"] for p in view["players"]]
        )
        self.assertEqual(public_snapshot(self.game)["players"], [])
        self.assertNotIn("role", view["roster"][0])

    def test_vent_permissions_connections_and_reconnect(self):
        node = next(v for v in game_map(self.game)["vents"] if v["room_id"] == "power")
        for p in [self.imp, self.crew]:
            p.x, p.y = node["x"], node["y"]
            p.save()
        with self.assertRaises(RuleError):
            self.action(self.crew, "vent.enter", vent_id=node["id"])
        self.action(self.imp, "vent.enter", vent_id=node["id"])
        own = private_snapshot(self.game, self.imp.player_id)
        self.assertTrue(own["is_in_vent"])
        with self.assertRaises(RuleError):
            self.action(self.imp, "vent.travel", vent_id="not-linked")
        view = public_snapshot(self.game, viewer_id=self.crew.player_id)
        self.assertNotIn(
            appearance_id(self.game, self.imp), [p["id"] for p in view["players"]]
        )
        self.now += timedelta(seconds=2)
        self.action(self.imp, "vent.exit")
        self.imp.refresh_from_db()
        self.assertFalse(self.imp.is_in_vent)

    def test_sabotage_timeout_and_emergency_block(self):
        self.action(self.imp, "sabotage.start", kind="oxygen")
        self.crew.x, self.crew.y = 2930, 1970
        self.crew.save()
        with self.assertRaises(RuleError) as error:
            self.action(self.crew, "meeting.call")
        self.assertEqual(error.exception.code, "CRITICAL_ACTIVE")
        self.now += timedelta(seconds=91)
        tick(self.room.code, now=self.now)
        self.game.refresh_from_db()
        self.assertEqual(self.game.winner, "impostor")

    def test_challenges_are_typed_and_kind_specific(self):
        for kind in KINDS:
            seed = challenge(kind)
            self.assertFalse(valid_solution(kind, seed, []), kind)
            self.assertFalse(valid_solution(kind, seed, [True]), kind)

    def test_ghost_tasks_retained(self):
        from game.services.simulation import progress

        before = progress(self.game)
        self.crew.alive = False
        self.crew.save()
        self.assertEqual(progress(self.game), before)

    def test_transport_never_broadcasts_world(self):
        from game.services.transport import publish_update

        with patch("game.services.transport.get_channel_layer") as layer, patch(
            "game.services.transport.async_to_sync"
        ) as sync:
            publish_update(
                self.room.code,
                public_snapshot(self.game),
                [{"type": "task.challenge", "task_id": "secret"}],
            )
        event = sync.return_value.call_args.args[1]
        self.assertEqual(
            event["snapshot"],
            {"protocol_version": 2, "state_version": self.game.state_version},
        )
        self.assertEqual(event["events"], [])

    def test_all_twenty_server_validators_and_replay(self):
        from game.tasks import CATALOG

        task = self.game.tasks.filter(player_id=self.crew.player_id).first()
        point = next(
            p for p in game_map(self.game)["tasks"] if p["point"] == task.task_point
        )
        self.crew.x, self.crew.y = point["x"], point["y"]
        self.crew.save()
        for kind in KINDS:
            task.task_type = kind
            task.stage = 0
            task.stage_total = 1
            task.is_completed = False
            task.started_at = None
            task.challenge = []
            task.save()
            self.action(self.crew, "task.begin", task_id=str(task.pk))
            task.refresh_from_db()
            seed = task.challenge
            solutions = {
                "medical_scan": [seed[0], 3],
                "upload": [seed[0]],
                "sample_analysis": [seed[0]],
                "oxygen_filters": [3, 3, 3, *seed],
                "coolant_valves": [v for n in seed for v in [n, n, n]],
            }
            solution = solutions.get(kind, seed)
            with self.assertRaises(RuleError):
                self.action(
                    self.crew, "task.complete", task_id=str(task.pk), solution=solution
                )
            self.now += timedelta(seconds=CATALOG[kind]["seconds"] + 1)
            self.action(
                self.crew, "task.complete", task_id=str(task.pk), solution=solution
            )
            task.refresh_from_db()
            self.assertTrue(task.is_completed, kind)
            with self.assertRaises(RuleError):
                self.action(
                    self.crew, "task.complete", task_id=str(task.pk), solution=solution
                )

    def test_reactor_requires_two_distinct_live_holds(self):
        self.action(self.imp, "sabotage.start", kind="reactor")
        sabotage = self.game.sabotages.get(kind="reactor")
        actors = list(self.game.player_states.filter(role="crew")[:2])
        panels = [
            p for p in game_map(self.game)["sabotage_panels"] if p["type"] == "reactor"
        ]
        for actor, panel in zip(actors, panels):
            actor.x, actor.y = panel["x"], panel["y"]
            actor.save()
            self.action(
                actor,
                "sabotage.repair.begin",
                sabotage_id=str(sabotage.pk),
                panel_id=panel["id"],
            )
        sabotage.refresh_from_db()
        self.assertNotEqual(sabotage.status, "resolved")
        self.now += timedelta(seconds=1.1)
        self.action(
            actors[0],
            "sabotage.repair.begin",
            sabotage_id=str(sabotage.pk),
            panel_id=panels[0]["id"],
        )
        sabotage.refresh_from_db()
        self.assertEqual(sabotage.status, "resolved")

    def test_oxygen_distinct_codes_and_repair(self):
        self.action(self.imp, "sabotage.start", kind="oxygen")
        sabotage = self.game.sabotages.get(kind="oxygen")
        panels = [
            p for p in game_map(self.game)["sabotage_panels"] if p["type"] == "oxygen"
        ]
        for i, panel in enumerate(panels):
            self.crew.x, self.crew.y = panel["x"], panel["y"]
            self.crew.save()
            self.action(
                self.crew,
                "sabotage.repair.begin",
                sabotage_id=str(sabotage.pk),
                panel_id=panel["id"],
            )
            private = private_snapshot(self.game, self.crew.player_id)
            self.assertEqual(
                private["repair"]["challenge"], sabotage.challenge[panel["id"]]
            )
            self.assertNotIn(
                "challenge",
                public_snapshot(self.game, viewer_id=self.crew.player_id)["sabotages"][
                    0
                ],
            )
            self.now += timedelta(seconds=3)
            self.action(
                self.crew,
                "sabotage.repair.complete",
                sabotage_id=str(sabotage.pk),
                panel_id=panel["id"],
                solution=sabotage.challenge[panel["id"]],
            )
            sabotage.refresh_from_db()
            self.assertEqual(sabotage.status, "resolved" if i else "repairing")

    def test_wall_and_light_occlusion(self):
        from game.v2 import visible
        from game.models import SabotageInstance

        self.crew.x, self.crew.y = 2900, 1970
        self.crew.save()
        self.assertTrue(visible(self.game, self.crew, {"x": 3200, "y": 1970}, self.now))
        SabotageInstance.objects.create(
            game=self.game,
            kind="lights",
            started_at=self.now,
            initiator=self.imp.player,
        )
        self.assertFalse(
            visible(self.game, self.crew, {"x": 3200, "y": 1970}, self.now)
        )
        self.assertFalse(
            visible(self.game, self.crew, {"x": 2900, "y": 1660}, self.now)
        )

    def test_chat_separates_ghosts_and_rate_limits(self):
        from game.services.simulation import start_meeting

        start_meeting(self.game, self.room, self.crew, self.now)
        self.game.save()
        ghost = (
            self.game.player_states.filter(role="crew").exclude(pk=self.crew.pk).first()
        )
        ghost.alive = False
        ghost.save()
        self.action(ghost, "meeting.chat.send", text="<script>ghost</script>")
        self.action(self.crew, "meeting.chat.send", text="living")
        with self.assertRaises(RuleError):
            self.action(self.crew, "meeting.chat.send", text="spam")
        living = public_snapshot(self.game, viewer_id=self.crew.player_id)["meeting"][
            "messages"
        ]
        dead = public_snapshot(self.game, viewer_id=ghost.player_id)["meeting"][
            "messages"
        ]
        self.assertEqual([m["text"] for m in living], ["living"])
        self.assertEqual([m["text"] for m in dead], ["<script>ghost</script>"])

    def test_terminals_require_proximity_and_comms(self):
        with self.assertRaises(RuleError):
            self.action(self.crew, "terminal.use", terminal_id="security")
        terminal = next(
            t for t in game_map(self.game)["terminals"] if t["type"] == "admin"
        )
        self.crew.x, self.crew.y = terminal["x"], terminal["y"]
        self.crew.save()
        self.action(self.crew, "terminal.use", terminal_id=terminal["id"])
        self.assertEqual(
            private_snapshot(self.game, self.crew.player_id)["observation"]["type"],
            "admin",
        )
        self.action(self.imp, "sabotage.start", kind="comms")
        self.assertIsNone(
            private_snapshot(self.game, self.crew.player_id)["observation"]
        )
        self.action(self.crew, "terminal.use", terminal_id="")

    def test_kill_alias_and_wall_guard(self):
        self.imp.x, self.imp.y = 2930, 1970
        self.imp.kill_available_at = self.now
        self.imp.save()
        self.crew.x, self.crew.y = 2950, 1970
        self.crew.save()
        with self.assertRaises(RuleError):
            self.action(
                self.imp, "player.kill", target_player_id=str(self.crew.player_id)
            )
        self.action(
            self.imp,
            "player.kill",
            target_player_id=appearance_id(self.game, self.crew),
        )
        self.crew.refresh_from_db()
        self.assertFalse(self.crew.alive)

    def test_optional_abilities_and_expiry(self):
        self.game.settings["special_roles"] = True
        self.game.save()
        self.crew.special_role = "technician"
        self.crew.save()
        node = next(v for v in game_map(self.game)["vents"] if v["room_id"] == "power")
        self.crew.x, self.crew.y = node["x"], node["y"]
        self.crew.save()
        self.action(self.crew, "vent.enter", vent_id=node["id"])
        tick(self.room.code, now=self.now + timedelta(seconds=21))
        self.crew.refresh_from_db()
        self.assertFalse(self.crew.is_in_vent)
        self.assertGreater(self.crew.vent_available_at, self.now)
        self.crew.special_role = "tracker"
        self.crew.ability_available_at = None
        self.crew.save()
        self.action(
            self.crew, "player.ability.use", target_player_id=str(self.imp.player_id)
        )
        self.crew.refresh_from_db()
        self.assertIn("tracking", self.crew.ability_state)
        with self.assertRaises(RuleError):
            self.action(
                self.crew,
                "player.ability.use",
                target_player_id=str(self.imp.player_id),
            )
        self.imp.special_role = "mimic"
        self.imp.save()
        old_alias = appearance_id(self.game, self.imp)
        self.action(
            self.imp, "player.ability.use", target_player_id=str(self.crew.player_id)
        )
        self.imp.refresh_from_db()
        self.assertNotEqual(appearance_id(self.game, self.imp), old_alias)
        self.crew.alive = False
        self.crew.ability_available_at = None
        self.crew.save()
        target = self.game.player_states.filter(role="crew", alive=True).first()
        self.action(
            self.crew, "player.ability.use", target_player_id=str(target.player_id)
        )
        target.refresh_from_db()
        self.assertIn("shield_until", target.ability_state)

    def test_stop_input_does_not_wait_for_movement_tokens(self):
        self.crew.move_tokens = 0
        self.crew.last_move_at = self.now
        self.crew.direction_x = 1
        self.crew.save()
        self.action(self.crew, "player.move", seq=1, direction={"x": 0, "y": 0})
        self.crew.refresh_from_db()
        self.assertEqual(self.crew.direction_x, 0)
        with self.assertRaises(RuleError):
            self.action(self.crew, "player.move", seq=2, direction={"x": 1, "y": 0})

    def test_clock_keeps_offline_critical_deadlines_but_skips_idle_rooms(self):
        from game.management.commands.run_game_worker import active_room_codes

        self.assertNotIn(self.room.code, list(active_room_codes()))
        self.action(self.imp, "sabotage.start", kind="oxygen")
        self.assertIn(self.room.code, list(active_room_codes()))
        self.game.sabotages.update(status="resolved")
        self.assertNotIn(self.room.code, list(active_room_codes()))
        self.room.memberships.filter(player_id=self.crew.player_id).update(
            is_connected=True
        )
        self.assertIn(self.room.code, list(active_room_codes()))

    def test_locked_door_blocks_clock_and_opens_after_absolute_expiry(self):
        from game.maps import closed_doors
        from game.physics import blocked

        door = next(
            d for d in game_map(self.game)["doors"] if d["id"] == "power--security"
        )
        self.crew.x, self.crew.y = door["bounds"]["x"] - 25, door["bounds"]["y"] + 90
        self.crew.save()
        self.action(self.imp, "sabotage.start", kind="doors", group=door["group"])
        self.action(self.crew, "player.move", seq=1, direction={"x": 1, "y": 0})
        tick(self.room.code, now=self.now + timedelta(seconds=0.2))
        self.crew.refresh_from_db()
        self.assertLessEqual(self.crew.x, door["bounds"]["x"] - 14)
        self.now += timedelta(seconds=11)
        self.action(self.crew, "player.move", seq=2, direction={"x": 1, "y": 0})
        tick(self.room.code, now=self.now + timedelta(seconds=0.2))
        self.crew.refresh_from_db()
        self.assertGreater(self.crew.x, door["bounds"]["x"])

    def test_late_repair_cannot_reverse_a_critical_deadline(self):
        self.action(self.imp, "sabotage.start", kind="oxygen")
        sabotage = self.game.sabotages.get(kind="oxygen")
        panel = next(
            p for p in game_map(self.game)["sabotage_panels"] if p["type"] == "oxygen"
        )
        self.crew.x, self.crew.y = panel["x"], panel["y"]
        self.crew.save()
        self.now += timedelta(seconds=91)
        self.action(
            self.crew,
            "sabotage.repair.begin",
            sabotage_id=str(sabotage.pk),
            panel_id=panel["id"],
        )
        self.game.refresh_from_db()
        sabotage.refresh_from_db()
        self.assertEqual(self.game.winner, "impostor")
        self.assertEqual(sabotage.status, "failed")

    def test_camera_respects_mimic_and_vent_privacy(self):
        self.game.settings["special_roles"] = True
        self.game.save()
        target = (
            self.game.player_states.filter(role="crew").exclude(pk=self.crew.pk).first()
        )
        camera = next(
            c for c in game_map(self.game)["cameras"] if c["room_id"] == "security"
        )
        self.crew.x, self.crew.y = 2930, 1230
        self.crew.save()
        self.imp.x, self.imp.y = 2930, 1280
        self.imp.special_role = "mimic"
        self.imp.save()
        target.x, target.y = 650, 2120
        target.save()
        self.action(
            self.imp, "player.ability.use", target_player_id=str(target.player_id)
        )
        self.action(
            self.crew, "terminal.use", terminal_id="security", camera_id=camera["id"]
        )
        observation = private_snapshot(self.game, self.crew.player_id)["observation"]
        self.imp.refresh_from_db()
        alias = appearance_id(self.game, self.imp)
        appearance = next(p for p in observation["players"] if p["id"] == alias)
        self.assertEqual(appearance["nickname"], target.player.nickname)
        self.assertEqual(appearance["color"], target.color)
        self.imp.is_in_vent = True
        self.imp.save()
        self.assertNotIn(
            alias,
            [
                p["id"]
                for p in private_snapshot(self.game, self.crew.player_id)[
                    "observation"
                ]["players"]
            ],
        )
        with self.assertRaises(RuleError):
            self.action(self.imp, "terminal.use", terminal_id="security")
