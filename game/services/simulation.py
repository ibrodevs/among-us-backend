from game import metrics
from game.services.roles import spawn_points

"""Authoritative actions and clock. Every writer locks Room, then Game.

A durable 10 Hz worker owns elapsed time; browsers submit directions only.
Multiple workers serialize on the same Room and last_tick_at prevents double steps.
"""

import math
import secrets
from collections import Counter
from datetime import timedelta
from uuid import UUID

from django.db.models import Count, Q
from django.db import transaction
from django.utils import timezone

from game.models import (
    Corpse,
    GameSession,
    Meeting,
    PlayerGameState,
    TaskAssignment,
    Vote,
)
from game.physics import MAP, TASKS, move
from game.maps import game_map, task_stations, closed_doors
from rooms.models import Room, RoomMembership


class RuleError(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(detail)


def require(condition, code="FORBIDDEN", detail="Действие недоступно"):
    if not condition:
        raise RuleError(code, detail)


def uuid_value(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise RuleError("BAD_PAYLOAD", "Некорректный идентификатор") from None


def near(state, point, radius):
    return math.hypot(state.x - point["x"], state.y - point["y"]) <= radius


def progress(game):
    ctx = getattr(game, "_frame", None)
    if ctx is not None:
        obligated = {
            s.player_id
            for s in ctx["states"]
            if s.role == "crew" and (s.alive or game.settings.get("ghost_tasks", True))
        } & ctx["members"]
        tasks = [t for t in ctx["tasks"] if t.player_id in obligated]
        return sum(t.is_completed for t in tasks), len(tasks)
    # Dead crew cannot perform tasks: their outstanding obligations are retired.
    living = game.player_states.filter(
        role="crew",
        **(
            {}
            if game.map_version == 2 and game.settings.get("ghost_tasks", True)
            else {"alive": True}
        )
    ).values("player_id")
    tasks = game.tasks.filter(player_id__in=living)
    if game.map_version == 2:
        tasks = tasks.filter(
            player_id__in=RoomMembership.objects.filter(room_id=game.room_id).values(
                "player_id"
            )
        )
    counts = tasks.aggregate(
        done=Count("pk", filter=Q(is_completed=True)), total=Count("pk")
    )
    return counts["done"], counts["total"]


def evaluate_win(game, room, now):
    living = game.player_states.filter(alive=True)
    impostors = living.filter(role="impostor").count()
    crew = living.filter(role="crew").count()
    completed, total = progress(game)
    winner, reason = (
        ("crew", "impostors_eliminated")
        if impostors == 0
        else (
            ("impostor", "parity")
            if impostors >= crew
            else (
                ("crew", "tasks_completed")
                if total > 0 and completed == total
                else ("", "")
            )
        )
    )
    if winner:
        game.phase, game.winner, game.finish_reason, game.finished_at = (
            "finished",
            winner,
            reason,
            now,
        )
        room.status = "finished"
        room.save(update_fields=["status"])
        game.player_states.update(direction_x=0, direction_y=0)


def start_meeting(game, room, state, now, corpse=None):
    game.phase = room.status = "meeting"
    room.save(update_fields=["status"])
    game.player_states.update(direction_x=0, direction_y=0)
    if game.map_version == 2:
        game.player_states.update(is_in_vent=False, current_vent_id="", observing="")
        # Meeting positions are public. Never expose a previously hidden tunnel
        # destination by reusing the exploration coordinates in the roster view.
        for index, participant in enumerate(game.player_states.order_by("player_id")):
            spawn = spawn_points(game)[index]
            participant.x, participant.y = spawn["x"], spawn["y"]
            participant.vent_transition_started_at = None
            participant.ability_state = {
                key: value
                for key, value in participant.ability_state.items()
                if key not in ["mimic_until", "mimic_target"]
            }
            participant.ability_state["appearance_epoch"] = secrets.token_hex(12)
            participant.save(
                update_fields=["x", "y", "vent_transition_started_at", "ability_state"]
            )
        game.sabotages.filter(
            kind__in=["reactor", "oxygen"], status__in=["active", "repairing"]
        ).update(status="resolved", resolved_at=now)
    # Opening a meeting invalidates unfinished task attempts.
    game.tasks.filter(is_completed=False).update(started_at=None, challenge=[])
    meeting = Meeting.objects.create(
        game=game,
        number=game.meetings.count() + 1,
        reporter_id=state.player_id,
        corpse=corpse,
        discussion_ends_at=now
        + timedelta(seconds=game.settings.get("discussion_seconds", 30)),
        voting_ends_at=now
        + timedelta(
            seconds=game.settings.get("discussion_seconds", 30)
            + game.settings.get("voting_seconds", 30)
        ),
    )
    if corpse:
        corpse.reported_at = now
        corpse.save(update_fields=["reported_at"])
    return {"type": "meeting.started", "meeting_id": str(meeting.pk)}


def finish_vote(game, room, meeting, now):
    counts = Counter(
        str(v) if v else "skip"
        for v in meeting.votes.values_list("target_id", flat=True)
    )
    candidates = {key: value for key, value in counts.items() if key != "skip"}
    leaders = (
        [key for key, value in candidates.items() if value == max(candidates.values())]
        if candidates
        else []
    )
    ejected = (
        leaders[0]
        if len(leaders) == 1 and candidates[leaders[0]] > counts.get("skip", 0)
        else None
    )
    if ejected:
        game.player_states.filter(player_id=ejected).update(
            alive=False, direction_x=0, direction_y=0
        )
    meeting.result = {
        "ejected_player_id": ejected,
        "counts": dict(counts),
        "next_phase": "playing",
    }
    if game.map_version == 2 and game.settings.get("confirm_ejects") and ejected:
        meeting.result["ejected_role"] = game.player_states.get(player_id=ejected).role
    meeting.result_ends_at = now + timedelta(seconds=5)
    if game.map_version == 2:
        meeting.result["presentation_until"] = meeting.result_ends_at.isoformat()
    meeting.save(update_fields=["result", "result_ends_at"])
    game.last_meeting_result = meeting.result
    evaluate_win(game, room, now)
    return {"type": "meeting.ended", **meeting.result}


def public_snapshot(game, now=None, viewer_id=None):
    now = now or timezone.now()
    completed, total = progress(game)
    ctx = getattr(game, "_frame", None)
    meeting = (
        (
            ctx["meeting"]
            if ctx is not None
            else game.meetings.filter(finished_at__isnull=True)
            .order_by("-number")
            .first()
        )
        if game.phase == "meeting"
        else None
    )
    data = {
        "type": "game.snapshot",
        "protocol_version": 1,
        "game_id": str(game.pk),
        "state_version": game.state_version,
        "server_time": now.isoformat(),
        "phase": game.phase,
        "players": [
            {
                "id": str(s.player_id),
                "nickname": s.player.nickname,
                "x": s.x,
                "y": s.y,
                "alive": s.alive,
            }
            for s in (
                game.player_states.select_related("player").order_by("player_id")
                if game.map_version == 1
                else []
            )
        ],
        "bodies": [
            {"id": str(c.pk), "player_id": str(c.player_id), "x": c.x, "y": c.y}
            for c in (
                game.corpses.filter(reported_at__isnull=True)
                if game.map_version == 1
                else []
            )
        ],
        "tasks_completed": completed,
        "tasks_total": total,
        "meeting": None,
        "last_meeting_result": game.last_meeting_result,
    }
    if meeting and game.phase == "meeting":
        stage = (
            "result"
            if meeting.result_ends_at
            else ("discussion" if now < meeting.discussion_ends_at else "voting")
        )
        data["meeting"] = {
            "id": str(meeting.pk),
            "reporter_id": str(meeting.reporter_id),
            "stage": stage,
            "deadline_at": (
                meeting.result_ends_at
                or (
                    meeting.discussion_ends_at
                    if stage == "discussion"
                    else meeting.voting_ends_at
                )
            ).isoformat(),
            "votes_cast": (
                len(ctx["votes"]) if ctx is not None else meeting.votes.count()
            ),
            "alive_voters": (
                sum(s.alive for s in ctx["states"])
                if ctx is not None
                else game.player_states.filter(alive=True).count()
            ),
            "result": meeting.result,
            **(
                {
                    "votes": [
                        {
                            "voter_id": str(v.voter_id),
                            "target_id": str(v.target_id) if v.target_id else None,
                        }
                        for v in (
                            ctx["votes"] if ctx is not None else meeting.votes.all()
                        )
                    ]
                }
                if game.map_version == 2
                and not game.settings.get("anonymous_votes", True)
                else {}
            ),
        }
    if game.phase == "finished":
        data["result"] = {
            "winner": game.winner,
            "reason": game.finish_reason,
            "players_with_roles": [
                {"id": str(s.player_id), "nickname": s.player.nickname, "role": s.role}
                for s in (
                    ctx["states"]
                    if ctx is not None
                    else game.player_states.select_related("player")
                )
            ],
        }
    if game.map_version == 2:
        from game.v2 import enrich_public

        data = enrich_public(game, data, viewer_id, now)
    return data


def private_snapshot(game, player_id):
    ctx = getattr(game, "_frame", None)
    state = next(
        (
            s
            for s in (
                ctx["states"]
                if ctx is not None
                else getattr(game, "_snapshot_states", [])
            )
            if str(s.player_id) == str(player_id)
        ),
        None,
    ) or game.player_states.get(player_id=player_id)
    task_models = (
        [t for t in ctx["tasks"] if str(t.player_id) == str(player_id)]
        if ctx is not None
        else list(game.tasks.filter(player_id=player_id).order_by("task_point"))
    )
    meeting = (
        (
            ctx["meeting"]
            if ctx is not None
            else game.meetings.filter(finished_at__isnull=True).first()
        )
        if game.phase == "meeting"
        else None
    )
    data = {
        "type": "game.self",
        "protocol_version": 1,
        "game_id": str(game.pk),
        "state_version": game.state_version,
        "role": state.role,
        "alive": state.alive,
        "last_move_seq": state.last_move_seq,
        "kill_available_at": (
            state.kill_available_at.isoformat() if state.kill_available_at else None
        ),
        "emergency_used": state.emergency_used,
        "has_voted": bool(
            meeting
            and (
                any(str(v.voter_id) == str(player_id) for v in ctx["votes"])
                if ctx is not None
                else meeting.votes.filter(voter_id=player_id).exists()
            )
        ),
        "tasks": [
            {
                "id": str(t.pk),
                "task_type": t.task_type,
                "task_point": t.task_point,
                "is_completed": t.is_completed,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "challenge": t.challenge,
                **task_stations(game).get(
                    t.extra.get("destination") if t.stage else t.task_point, {}
                ),
            }
            for t in task_models
        ],
    }

    if game.map_version == 2:
        from game.v2 import enrich_private

        data = enrich_private(game, state, data, task_models=task_models)
    return data


@metrics.timed("command_processing_ms")
@transaction.atomic
def command(code, player_id, payload, now=None):
    now = now or timezone.now()
    room = Room.objects.select_for_update().filter(code=code).first()
    require(
        room and RoomMembership.objects.filter(room=room, player_id=player_id).exists(),
        "UNAUTHORIZED",
        "Нет доступа к комнате",
    )
    game = GameSession.objects.select_for_update().filter(room=room).first()
    require(game is not None, "INVALID_PHASE", "Матч ещё не начат")
    require(game.phase != "finished", "INVALID_PHASE", "Матч завершён")
    state = game.player_states.get(player_id=player_id)
    ghost_allowed = game.map_version == 2 and payload["type"] in [
        "player.move",
        "task.begin",
        "task.complete",
        "meeting.chat.send",
        "player.ability.use",
    ]
    ghost_allowed = ghost_allowed or (
        game.map_version == 2
        and payload["type"] == "sabotage.start"
        and game.settings.get("ghost_sabotage", False)
    )
    require(state.alive or ghost_allowed, "FORBIDDEN", "Вы наблюдаете за матчем")
    kind = payload["type"]
    events = []
    if game.map_version == 2:
        from game.v2 import handle_command, advance_world

        # High-frequency input only changes intent; the mandatory clock advances
        # deadlines/abilities once per tick instead of rescanning 20 actors for
        # every movement packet. Other actions still settle deadlines first.
        if (
            kind != "player.move"
            and advance_world(game, room, now)
            and game.phase == "finished"
        ):
            game.state_version += 1
            game.save()
            return [], public_snapshot(game, now), private_snapshot(game, player_id)
        handled, extra_events = handle_command(game, room, state, payload, now)
        if handled:
            game.state_version += 1
            game.save()
            return (
                extra_events,
                public_snapshot(game, now),
                private_snapshot(game, player_id),
            )
        require(not state.is_in_vent, "FORBIDDEN", "Сначала выйдите из тоннеля")
    if kind == "vote.cast":
        require(game.phase == "meeting", "INVALID_PHASE", "Нет активного собрания")
        meeting = game.meetings.get(finished_at__isnull=True)
        require(
            meeting.discussion_ends_at <= now < meeting.voting_ends_at
            and not meeting.result_ends_at,
            "INVALID_PHASE",
            "Голосование закрыто",
        )
        require(
            not meeting.votes.filter(voter_id=player_id).exists(),
            "ALREADY_DONE",
            "Голос уже принят",
        )
        require("target_player_id" in payload, "BAD_PAYLOAD", "Укажите игрока или Skip")
        target = (
            uuid_value(payload["target_player_id"])
            if payload["target_player_id"] is not None
            else None
        )
        require(
            target is None
            or game.player_states.filter(player_id=target, alive=True).exists(),
            "BAD_PAYLOAD",
            "Недопустимая цель",
        )
        require(
            game.settings.get("self_vote", True) or target != state.player_id,
            "FORBIDDEN",
            "Self voting disabled",
        )
        Vote.objects.create(meeting=meeting, voter_id=player_id, target_id=target)
        events.append(
            {
                "type": "vote.updated",
                "votes_cast": meeting.votes.count(),
                "alive_voters": game.player_states.filter(alive=True).count(),
            }
        )
        if meeting.votes.count() == game.player_states.filter(alive=True).count():
            events.append(finish_vote(game, room, meeting, now))
    else:
        require(
            game.phase == "playing", "INVALID_PHASE", "Дождитесь завершения собрания"
        )
        if kind == "player.move":
            seq, direction = payload.get("seq"), payload.get("direction")
            require(
                type(seq) is int
                and 0 < seq <= 9007199254740991
                and isinstance(direction, dict),
                "BAD_PAYLOAD",
                "Некорректное направление",
            )
            dx, dy = direction.get("x"), direction.get("y")
            require(
                type(dx) in (int, float)
                and type(dy) in (int, float)
                and abs(dx) <= 1
                and abs(dy) <= 1
                and math.isfinite(dx)
                and math.isfinite(dy),
                "BAD_PAYLOAD",
                "Недопустимое направление",
            )
            require(seq > state.last_move_seq, "STALE_SEQ", "Устаревшая команда")
            elapsed = (
                max(0, (now - state.last_move_at).total_seconds())
                if state.last_move_at
                else 1
            )
            available = min(2, state.move_tokens + elapsed * 10)
            stopping = game.map_version == 2 and dx == 0 and dy == 0
            require(
                available >= 1 or stopping, "RATE_LIMITED", "Слишком частые команды"
            )
            state.move_tokens = available if stopping else available - 1
            if (
                stopping
                and state.last_move_at
                and (state.direction_x or state.direction_y)
            ):
                # Settle the fraction of the current tick before clearing input,
                # so short taps do not disappear between clock iterations.
                since = max(game.last_tick_at or state.last_move_at, state.last_move_at)
                seconds = min(0.15, max(0, (now - since).total_seconds()))
                if (now - state.last_move_at).total_seconds() < 0.35:
                    state.x, state.y = move(
                        state.x,
                        state.y,
                        state.direction_x,
                        state.direction_y,
                        seconds,
                        {
                            **game_map(game),
                            "speed": game.settings.get("speed", 220),
                            **({"walls": []} if not state.alive else {}),
                        },
                        [] if not state.alive else closed_doors(game, now),
                    )
            (
                state.direction_x,
                state.direction_y,
                state.last_move_seq,
                state.last_move_at,
            ) = (dx, dy, seq, now)
            state.save(
                update_fields=[
                    "direction_x",
                    "direction_y",
                    "move_tokens",
                    "last_move_seq",
                    "last_move_at",
                    "x",
                    "y",
                ]
            )
            if stopping:
                game.state_version += 1
                game.save(update_fields=["state_version"])
                return [], None, private_snapshot(game, player_id)
            return [], None, None
        elif kind == "player.kill":
            require(state.role == "impostor")
            if game.map_version == 2:
                from game.v2 import appearance_id, visible, future

                target = next(
                    (
                        p
                        for p in game.player_states.all()
                        if appearance_id(game, p) == payload.get("target_player_id")
                    ),
                    None,
                )
                require(
                    target
                    and not target.is_in_vent
                    and visible(game, state, {"x": target.x, "y": target.y}, now)
                )
                require(
                    not future(target.ability_state.get("shield_until"), now),
                    "SHIELDED",
                    "Target protected",
                )
            else:
                target = game.player_states.filter(
                    player_id=uuid_value(payload.get("target_player_id"))
                ).first()
            require(
                target
                and target.alive
                and target.role == "crew"
                and target.player_id != state.player_id,
                "FORBIDDEN",
                "Недопустимая цель",
            )
            require(
                near(state, {"x": target.x, "y": target.y}, 90),
                "OUT_OF_RANGE",
                "Цель слишком далеко",
            )
            require(
                state.kill_available_at is None or now >= state.kill_available_at,
                "COOLDOWN",
                "Перезарядка",
            )
            if game.map_version == 2:
                from game.v2 import record_effect

                record_effect(game, "kill", target, now)
            target.alive, target.direction_x, target.direction_y = False, 0, 0
            target.save(update_fields=["alive", "direction_x", "direction_y"])
            state.kill_available_at = now + timedelta(
                seconds=game.settings.get("kill_cooldown", 25)
            )
            state.save(update_fields=["kill_available_at"])
            body = Corpse.objects.create(
                game=game, player_id=target.player_id, x=target.x, y=target.y
            )
            events.extend(
                [
                    {"type": "player.died", "player_id": str(target.player_id)},
                    {
                        "type": "body.spawned",
                        "body_id": str(body.pk),
                        "x": body.x,
                        "y": body.y,
                    },
                ]
            )
        elif kind in ("task.begin", "task.complete"):
            require(state.role == "crew")
            task = game.tasks.filter(
                pk=uuid_value(payload.get("task_id")), player_id=player_id
            ).first()
            require(task is not None, "FORBIDDEN", "Это не ваше задание")
            require(not task.is_completed, "ALREADY_DONE", "Задание уже выполнено")
            config = task_stations(game)[
                task.extra.get("destination") if task.stage else task.task_point
            ]
            require(near(state, config, 85), "OUT_OF_RANGE", "Подойдите к терминалу")
            if game.map_version == 2:
                from game.v2 import task_action

                events.extend(task_action(game, state, task, payload, now))
            elif kind == "task.begin":
                if task.started_at is None:
                    task.started_at = now
                    task.challenge = (
                        secrets.SystemRandom().sample(range(3), 3)
                        if task.task_type == "wires"
                        else (
                            [secrets.randbelow(4) for _ in range(4)]
                            if task.task_type == "sequence"
                            else []
                        )
                    )
                    task.save(update_fields=["started_at", "challenge"])
                state.direction_x = state.direction_y = 0
                state.save(update_fields=["direction_x", "direction_y"])
            else:
                require(
                    task.started_at is not None
                    and (now - task.started_at).total_seconds() >= config["seconds"],
                    "TOO_EARLY",
                    "Задание ещё не завершено",
                )
                solution = payload.get("solution")
                require(
                    isinstance(solution, list)
                    and all(type(v) is int for v in solution)
                    and solution == task.challenge,
                    "BAD_SOLUTION",
                    "Попробуйте ещё раз",
                )
                task.is_completed, task.completed_at = True, now
                task.save(update_fields=["is_completed", "completed_at"])
                done, total = progress(game)
                events.append(
                    {"type": "task.progress", "completed": done, "total": total}
                )
        elif kind == "body.report":
            body = game.corpses.filter(
                pk=uuid_value(payload.get("body_id")), reported_at__isnull=True
            ).first()
            require(body is not None, "ALREADY_DONE", "Тело уже зарегистрировано")
            require(
                near(state, {"x": body.x, "y": body.y}, 110),
                "OUT_OF_RANGE",
                "Подойдите ближе к телу",
            )
            if game.map_version == 2:
                from game.v2 import visible

                require(visible(game, state, {"x": body.x, "y": body.y}, now))
            events.append(start_meeting(game, room, state, now, body))
        elif kind == "meeting.call":
            require(
                game.map_version != 2
                or not game.sabotages.filter(
                    kind__in=["reactor", "oxygen"], status__in=["active", "repairing"]
                ).exists(),
                "CRITICAL_ACTIVE",
                "Repair the emergency first",
            )
            require(
                not state.emergency_used,
                "ALREADY_DONE",
                "Экстренное собрание уже использовано",
            )
            require(
                near(state, game_map(game)["emergency"], 85),
                "OUT_OF_RANGE",
                "Подойдите к центральному пульту",
            )
            state.emergency_used = True
            state.save(update_fields=["emergency_used"])
            events.append(start_meeting(game, room, state, now))
        else:
            raise RuleError("BAD_PAYLOAD", "Неизвестная команда")
    if game.phase == "playing":
        evaluate_win(game, room, now)
    game.state_version += 1
    game.save()
    if game.phase == "finished":
        events.append({"type": "game.ended", **public_snapshot(game, now)["result"]})
    return events, public_snapshot(game, now), private_snapshot(game, player_id)


@transaction.atomic
def tick(code, now=None):
    now = now or timezone.now()
    room = Room.objects.select_for_update().get(code=code)
    game = GameSession.objects.select_for_update().get(room=room)
    if game.phase == "finished":
        return None, []
    dt = (now - (game.last_tick_at or now)).total_seconds()
    if dt < 0.09:
        return None, []
    game.last_tick_at = now
    events = []
    changed = False
    if game.phase == "playing":
        for state in game.player_states.filter(
            **({} if game.map_version == 2 else {"alive": True})
        ):
            if state.is_in_vent:
                continue
            if (
                state.last_move_at
                and (now - state.last_move_at).total_seconds() < 0.35
                and (state.direction_x or state.direction_y)
            ):
                state.x, state.y = move(
                    state.x,
                    state.y,
                    state.direction_x,
                    state.direction_y,
                    min(dt, 0.15),
                    (
                        {
                            **game_map(game),
                            "walls": [],
                            "speed": game.settings.get("speed", 220),
                        }
                        if game.map_version == 2 and not state.alive
                        else {
                            **game_map(game),
                            "speed": game.settings.get(
                                "speed", game_map(game)["speed"]
                            ),
                        }
                    ),
                    (
                        []
                        if game.map_version == 2 and not state.alive
                        else closed_doors(game, now)
                    ),
                )
                state.save(update_fields=["x", "y"])
                for task in game.tasks.filter(
                    player_id=state.player_id,
                    is_completed=False,
                    started_at__isnull=False,
                ):
                    if not near(
                        state,
                        task_stations(game)[
                            (
                                task.extra.get("destination")
                                if task.stage
                                else task.task_point
                            )
                        ],
                        85,
                    ):
                        task.started_at = None
                        task.challenge = []
                        task.save(update_fields=["started_at", "challenge"])
                changed = True
                events.append(
                    {
                        "type": "player.moved",
                        "player_id": str(state.player_id),
                        "x": state.x,
                        "y": state.y,
                        "seq": state.last_move_seq,
                    }
                )
    elif game.phase == "meeting":
        meeting = game.meetings.get(finished_at__isnull=True)
        if meeting.result_ends_at:
            if now >= meeting.result_ends_at:
                meeting.finished_at = now
                meeting.save(update_fields=["finished_at"])
                game.corpses.filter(reported_at__isnull=True).update(reported_at=now)
                for index, state in enumerate(game.player_states.order_by("player_id")):
                    state.x, state.y = (
                        spawn_points(game)[index]["x"],
                        spawn_points(game)[index]["y"],
                    )
                    state.kill_available_at = now + timedelta(
                        seconds=game.settings.get("kill_cooldown", 25)
                    )
                    state.save(update_fields=["x", "y", "kill_available_at"])
                game.phase = room.status = "playing"
                room.save(update_fields=["status"])
                changed = True
        elif now >= meeting.voting_ends_at:
            events.append(finish_vote(game, room, meeting, now))
            changed = True
        elif now >= meeting.discussion_ends_at:
            changed = True
    if game.map_version == 2:
        from game.v2 import advance_world

        if advance_world(game, room, now):
            changed = True
    if changed:
        game.state_version += 1
    game.save()
    if game.phase == "finished":
        events.append({"type": "game.ended", **public_snapshot(game, now)["result"]})
    # Meeting snapshots refresh countdowns; idle games only emit on action/heartbeat.
    return (
        public_snapshot(game, now) if changed or game.phase == "meeting" else None
    ), events
