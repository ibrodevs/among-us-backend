"""Extensions to the existing locked match engine. No separate simulation loop."""

import math
import secrets
import uuid
from datetime import timedelta, datetime
from django.utils import timezone
from game.maps import game_map, active_rooms, closed_doors, task_stations
from game.models import PlayerGameState, MeetingMessage, DoorState, SabotageInstance
from game.physics import blocked
from game.tasks import CATALOG, challenge, valid_solution


def rules():
    from game.services.simulation import require, near, uuid_value

    return require, near, uuid_value


def iso(value):
    return value.isoformat() if value else None


def date(value):
    return datetime.fromisoformat(value) if value else None


def future(value, now):
    return bool(value and date(value) > now)


def room_at(game, state):
    return next(
        (
            r["id"]
            for r in game_map(game)["rooms"]
            if r["bounds"]["x"] <= state.x <= r["bounds"]["x"] + r["bounds"]["width"]
            and r["bounds"]["y"] <= state.y <= r["bounds"]["y"] + r["bounds"]["height"]
        ),
        None,
    )


def segment_hits(a, b, r):
    low, high = 0.0, 1.0
    for axis in ["x", "y"]:
        delta = b[axis] - a[axis]
        minimum = r[axis]
        maximum = minimum + r["width" if axis == "x" else "height"]
        if abs(delta) < 1e-9:
            if not minimum < a[axis] < maximum:
                return False
        else:
            p, q = (minimum - a[axis]) / delta, (maximum - a[axis]) / delta
            low = max(low, min(p, q))
            high = min(high, max(p, q))
            if high <= low:
                return False
    return high > 0 and low < 1


def visible(game, observer, point, now, radius=None, blockers=None, lights=None):
    if not observer.alive:
        return math.hypot(observer.x - point["x"], observer.y - point["y"]) <= 1200
    radius = radius or game.settings.get(
        "impostor_vision" if observer.role == "impostor" else "crew_vision", 520
    )
    if lights is None:
        lights = game.sabotages.filter(
            kind="lights", status__in=["active", "repairing"]
        ).exists()
    if observer.role == "crew" and lights:
        radius = min(radius, 150)
    if math.hypot(observer.x - point["x"], observer.y - point["y"]) > radius:
        return False
    a = {"x": observer.x, "y": observer.y}
    return not any(
        segment_hits(a, point, r)
        for r in (
            blockers
            if blockers is not None
            else [*game_map(game)["walls"], *closed_doors(game, now)]
        )
    )


def appearance_id(game, state):
    return str(
        uuid.uuid5(
            game.pk,
            str(state.pk) + str(state.ability_state.get("appearance_epoch", "0")),
        )
    )


def costume(state, states, now):
    if future(state.ability_state.get("mimic_until"), now):
        return next(
            (
                p
                for p in states
                if str(p.player_id) == state.ability_state.get("mimic_target")
            ),
            state,
        )
    return state


def record_effect(game, kind, state, now, **extra):
    effects = [e for e in game.effects if (now - date(e["at"])).total_seconds() < 3]
    game.effects = [
        *effects,
        dict(
            id=str(uuid.uuid4()), type=kind, x=state.x, y=state.y, at=iso(now), **extra
        ),
    ][-30:]


def enrich_public(game, data, viewer_id, now):
    states = list(game.player_states.select_related("player").order_by("player_id"))
    observer = next((s for s in states if str(s.player_id) == str(viewer_id)), None)
    data.update(
        protocol_version=2,
        map_id="asterion",
        map_version=2,
        map_mode=game.map_mode,
        settings=game.settings,
        roster=[
            dict(id=str(s.player_id), nickname=s.player.nickname, color=s.color)
            for s in states
        ],
    )
    locked = set(
        game.doors.filter(closed_until__gt=now).values_list("door_id", flat=True)
    )
    lights = game.sabotages.filter(
        kind="lights", status__in=["active", "repairing"]
    ).exists()
    blockers = [*game_map(game)["walls"], *closed_doors(game, now)]
    data["players"] = []
    data["bodies"] = []
    if observer:
        for s in states:
            own = s.player_id == observer.player_id
            allowed = (
                own
                or game.phase != "playing"
                or (
                    s.alive
                    and not s.is_in_vent
                    and visible(
                        game,
                        observer,
                        {"x": s.x, "y": s.y},
                        now,
                        blockers=blockers,
                        lights=lights,
                    )
                )
            )
            if not allowed or (s.is_in_vent and not own):
                continue
            disguise = (
                next(
                    (
                        q
                        for q in states
                        if str(q.player_id) == s.ability_state.get("mimic_target")
                    ),
                    None,
                )
                if future(s.ability_state.get("mimic_until"), now)
                else None
            )
            data["players"].append(
                dict(
                    id=(
                        str(s.player_id)
                        if own or game.phase != "playing"
                        else appearance_id(game, s)
                    ),
                    nickname=(disguise or s).player.nickname,
                    x=s.x,
                    y=s.y,
                    alive=s.alive,
                    color=(disguise or s).color,
                    ghost=not s.alive,
                    in_vent=s.is_in_vent,
                )
            )
        data["bodies"] = [
            dict(
                id=str(b.pk),
                player_id=str(b.player_id),
                x=b.x,
                y=b.y,
                color=next((s.color for s in states if s.player_id == b.player_id), 0),
            )
            for b in game.corpses.filter(reported_at__isnull=True)
            if visible(
                game,
                observer,
                {"x": b.x, "y": b.y},
                now,
                blockers=blockers,
                lights=lights,
            )
        ]
    data["terminal_activity"] = [
        t["id"]
        for t in game_map(game)["terminals"]
        if observer
        and visible(game, observer, t, now, blockers=blockers, lights=lights)
        and any(
            p.alive
            and not p.is_in_vent
            and p.observing == t["id"]
            and math.hypot(p.x - t["x"], p.y - t["y"]) <= 100
            for p in states
        )
    ]
    data["doors"] = [
        dict(
            id=d["id"],
            bounds=d["bounds"],
            closed=(game.map_mode == "compact" and not d["compact"])
            or d["id"] in locked,
        )
        for d in game_map(game)["doors"]
    ]
    data["sabotages"] = [
        dict(
            id=str(s.pk),
            kind=s.kind,
            status=s.status,
            deadline_at=iso(s.deadline_at),
            panels=[
                p for p in game_map(game)["sabotage_panels"] if p["type"] == s.kind
            ],
            repaired_panels=[
                key for key, value in s.repairs.items() if value.get("done")
            ],
        )
        for s in game.sabotages.filter(status__in=["active", "repairing"])
    ]
    data["effects"] = [
        e
        for e in game.effects
        if observer
        and visible(game, observer, e, now, blockers=blockers, lights=lights)
        and (now - date(e["at"])).total_seconds() < 2
    ]
    data["vision_radius"] = (
        1200
        if observer and not observer.alive
        else (
            game.settings.get("impostor_vision", 700)
            if observer and observer.role == "impostor"
            else (
                150
                if any(s["kind"] == "lights" for s in data["sabotages"])
                else game.settings.get("crew_vision", 520)
            )
        )
    )
    if data["meeting"] and observer:
        meeting = game.meetings.filter(finished_at__isnull=True).first()
        data["meeting"]["messages"] = [
            dict(
                id=str(m.pk),
                player_id=str(m.player_id),
                nickname=m.player.nickname,
                text=m.text,
                at=iso(m.created_at),
                ghost=m.ghost_channel,
            )
            for m in meeting.messages.filter(ghost_channel=not observer.alive)
            .select_related("player")
            .order_by("-created_at")[:50]
        ][::-1]
        data["meeting"]["channel"] = "ghost" if not observer.alive else "living"
    return data


def enrich_private(game, state, data):
    now = timezone.now()
    data.update(
        protocol_version=2,
        map_version=2,
        x=state.x,
        y=state.y,
        color=state.color,
        is_in_vent=state.is_in_vent,
        current_vent_id=state.current_vent_id,
        vent_available_at=iso(state.vent_available_at),
        special_role=(
            "guardian"
            if not state.alive
            and state.role == "crew"
            and game.settings.get("special_roles")
            else state.special_role
        ),
        ability_available_at=iso(state.ability_available_at),
        ability_state=state.ability_state,
        sabotage_available_at=iso(game.sabotage_available_at),
    )
    nodes = game_map(game)["vents"]
    v = next((v for v in nodes if v["id"] == state.current_vent_id), None)
    data["vent_connections"] = (
        [
            q
            for q in nodes
            if v
            and q["id"] in v["connected_vent_ids"]
            and q["room_id"] in active_rooms(game)
        ]
        if state.is_in_vent
        else []
    )
    for t, model in zip(
        data["tasks"],
        game.tasks.filter(player_id=state.player_id).order_by("task_point"),
    ):
        t.update(
            title=CATALOG[model.task_type]["title"],
            seconds=CATALOG[model.task_type]["seconds"],
            stage=model.stage,
            stage_total=model.stage_total,
            category=CATALOG[model.task_type]["category"],
        )
    data["communications_down"] = game.sabotages.filter(
        kind="comms", status__in=["active", "repairing"]
    ).exists()
    if data["communications_down"]:
        data["tasks"] = []
    data["ability_state"] = dict(state.ability_state)
    tracking = data["ability_state"].get("tracking")
    if tracking and not future(tracking.get("until"), now):
        data["ability_state"].pop("tracking")
    data["repair"] = None
    attempt = state.ability_state.get("repair")
    if attempt:
        sabotage = game.sabotages.filter(
            pk=attempt["sabotage_id"], status__in=["active", "repairing"]
        ).first()
        panel = next(
            (
                p
                for p in game_map(game)["sabotage_panels"]
                if p["id"] == attempt["panel_id"]
            ),
            None,
        )
        if sabotage and panel:
            data["repair"] = {
                **attempt,
                "kind": sabotage.kind,
                "challenge": sabotage.challenge.get(panel["id"], []),
                "panel": panel,
            }
    data["observation"] = None
    terminal = next(
        (t for t in game_map(game)["terminals"] if t["id"] == state.observing), None
    )
    if (
        terminal
        and state.alive
        and not state.is_in_vent
        and math.hypot(state.x - terminal["x"], state.y - terminal["y"]) <= 100
        and not game.sabotages.filter(
            kind="comms", status__in=["active", "repairing"]
        ).exists()
    ):
        observation_states = list(game.player_states.select_related("player"))
        if terminal["type"] == "admin":
            data["observation"] = dict(
                type="admin",
                counts={
                    r["id"]: sum(
                        1
                        for p in observation_states
                        if p.alive and not p.is_in_vent and room_at(game, p) == r["id"]
                    )
                    for r in game_map(game)["rooms"]
                    if r["id"] in active_rooms(game)
                },
            )
        elif terminal["type"] == "vitals":
            if not game.settings.get("special_roles") or state.special_role == "medic":
                data["observation"] = dict(
                    type="vitals",
                    players=[
                        dict(
                            id=str(p.player_id),
                            status=(
                                "dead"
                                if not p.alive
                                and (
                                    not game.corpses.filter(
                                        player_id=p.player_id
                                    ).exists()
                                    or game.corpses.filter(
                                        player_id=p.player_id,
                                        created_at__lt=now - timedelta(seconds=5),
                                    ).exists()
                                )
                                else "alive"
                            ),
                        )
                        for p in observation_states
                    ],
                )
        elif terminal["type"] == "cameras":
            camera = next(
                (
                    c
                    for c in game_map(game)["cameras"]
                    if c["id"] == state.ability_state.get("camera")
                ),
                game_map(game)["cameras"][0],
            )
            data["observation"] = dict(
                type="cameras",
                camera=camera,
                players=[
                    dict(
                        id=appearance_id(game, p),
                        nickname=costume(p, observation_states, now).player.nickname,
                        x=p.x,
                        y=p.y,
                        color=costume(p, observation_states, now).color,
                    )
                    for p in observation_states
                    if p.alive
                    and not p.is_in_vent
                    and math.hypot(p.x - camera["x"], p.y - camera["y"])
                    <= camera["radius"]
                    and not any(
                        segment_hits(camera, {"x": p.x, "y": p.y}, wall)
                        for wall in [*game_map(game)["walls"], *closed_doors(game, now)]
                    )
                ],
            )
    return data


def task_action(game, state, task, payload, now):
    require, near, _ = rules()
    definition = CATALOG[task.task_type]
    require(
        state.alive or (state.role == "crew" and game.settings.get("ghost_tasks", True))
    )
    require(
        not game.sabotages.filter(
            kind="comms", status__in=["active", "repairing"]
        ).exists(),
        "COMMS_DISABLED",
        "Сначала восстановите связь",
    )
    if payload["type"] == "task.begin":
        if task.started_at is None:
            task.started_at = now
            task.challenge = challenge(task.task_type)
            task.save(update_fields=["started_at", "challenge"])
        state.direction_x = state.direction_y = 0
        state.save(update_fields=["direction_x", "direction_y"])
        return [
            {
                "type": "task.challenge",
                "task_id": str(task.pk),
                "challenge": task.challenge,
                "stage": task.stage,
                "seconds": definition["seconds"],
            }
        ]
    require(
        task.started_at is not None
        and (now - task.started_at).total_seconds() >= definition["seconds"],
        "TOO_EARLY",
        "Терминал ещё работает",
    )
    require(
        valid_solution(task.task_type, task.challenge, payload.get("solution")),
        "BAD_SOLUTION",
        "Решение не принято",
    )
    if task.stage + 1 < task.stage_total:
        task.stage += 1
        task.started_at = None
        task.challenge = []
        task.save(update_fields=["stage", "started_at", "challenge"])
    else:
        task.is_completed = True
        task.completed_at = now
        task.save(update_fields=["is_completed", "completed_at"])
    return [
        {
            "type": "task.verified",
            "task_id": str(task.pk),
            "stage": task.stage,
            "is_completed": task.is_completed,
        }
    ]


class SabotageManager:
    """Uses the enclosing Room/Game transaction; deadlines survive worker restarts."""

    @staticmethod
    def start(game, state, payload, now):
        require, near, _ = rules()
        kind = payload.get("kind")
        require(
            state.role == "impostor"
            and (state.alive or game.settings.get("ghost_sabotage", False))
        )
        require(
            kind in ["lights", "reactor", "oxygen", "comms", "doors"],
            "BAD_PAYLOAD",
            "Неизвестная система",
        )
        require(not state.is_in_vent)
        require(
            game.sabotage_available_at is None or now >= game.sabotage_available_at,
            "COOLDOWN",
            "Система ещё восстанавливается",
        )
        require(
            not game.sabotages.filter(
                kind=kind, status__in=["active", "repairing"]
            ).exists(),
            "ALREADY_DONE",
            "Система уже отключена",
        )
        if kind in ["reactor", "oxygen"]:
            require(game.settings.get("critical_sabotages", True))
            require(
                not game.sabotages.filter(
                    kind__in=["reactor", "oxygen"], status__in=["active", "repairing"]
                ).exists(),
                "ALREADY_DONE",
                "Другая критическая авария уже активна",
            )
        sabotage = SabotageInstance.objects.create(
            game=game,
            kind=kind,
            started_at=now,
            deadline_at=(
                now
                + timedelta(
                    seconds=(
                        game.settings.get("critical_seconds", 90)
                        if kind in ["reactor", "oxygen"]
                        else 10
                    )
                )
                if kind in ["reactor", "oxygen", "doors"]
                else None
            ),
            initiator_id=state.player_id,
        )
        if kind == "doors":
            group = payload.get("group")
            doors = [
                d
                for d in game_map(game)["doors"]
                if d["group"] == group and (game.map_mode == "full" or d["compact"])
            ]
            require(bool(doors), "BAD_PAYLOAD", "Нет доступных дверей")
            for d in doors:
                require(
                    not any(
                        blocked(
                            p.x,
                            p.y,
                            {
                                "width": 6144,
                                "height": 4096,
                                "player_hitbox": 28,
                                "walls": [],
                            },
                            [d["bounds"]],
                        )
                        for p in game.player_states.filter(alive=True, is_in_vent=False)
                    ),
                    "OCCUPIED",
                    "Проход занят",
                )
            for d in doors:
                DoorState.objects.update_or_create(
                    game=game,
                    door_id=d["id"],
                    defaults={"closed_until": now + timedelta(seconds=10)},
                )
        sabotage.challenge = {
            p["id"]: (
                [secrets.randbelow(2) for _ in range(6)]
                if kind == "lights"
                else (
                    [secrets.randbelow(10) for _ in range(4)]
                    if kind == "oxygen"
                    else (
                        [secrets.randbelow(80) + 10, secrets.randbelow(360)]
                        if kind == "comms"
                        else []
                    )
                )
            )
            for p in game_map(game)["sabotage_panels"]
            if p["type"] == kind
        }
        sabotage.save(update_fields=["challenge"])
        game.sabotage_available_at = now + timedelta(seconds=30)
        return [{"type": "sabotage.started", "kind": kind}]

    @staticmethod
    def repair(game, state, payload, now):
        require, near, uuid_value = rules()
        require(state.alive and not state.is_in_vent)
        sabotage = game.sabotages.filter(
            pk=uuid_value(payload.get("sabotage_id")),
            status__in=["active", "repairing"],
        ).first()
        require(sabotage is not None, "ALREADY_DONE", "Авария устранена")
        panel = next(
            (
                p
                for p in game_map(game)["sabotage_panels"]
                if p["id"] == payload.get("panel_id") and p["type"] == sabotage.kind
            ),
            None,
        )
        require(
            panel and near(state, panel, 90),
            "OUT_OF_RANGE",
            "Подойдите к аварийному терминалу",
        )
        require(panel["room_id"] in active_rooms(game))
        sabotage.status = "repairing"
        if payload["type"] == "sabotage.repair.begin":
            previous = sabotage.repairs.get(panel["id"], {})
            same = (
                previous.get("player_id") == str(state.player_id)
                and previous.get("at")
                and (now - date(previous["at"])).total_seconds() < 1.5
            )
            sabotage.repairs[panel["id"]] = dict(
                player_id=str(state.player_id),
                at=iso(now),
                since=previous["since"] if same else iso(now),
                done=previous.get("done", False),
            )
            state.ability_state = {
                **state.ability_state,
                "repair": dict(sabotage_id=str(sabotage.pk), panel_id=panel["id"]),
            }
            state.save(update_fields=["ability_state"])
            if sabotage.kind == "reactor":
                holds = []
                for p in game_map(game)["sabotage_panels"]:
                    value = sabotage.repairs.get(p["id"])
                    actor = (
                        game.player_states.filter(
                            player_id=value["player_id"], alive=True, is_in_vent=False
                        ).first()
                        if value
                        else None
                    )
                    if (
                        p["type"] == "reactor"
                        and value
                        and actor
                        and near(actor, p, 90)
                        and (now - date(value["at"])).total_seconds() < 1.5
                        and (now - date(value["since"])).total_seconds() >= 1
                    ):
                        holds.append(value["player_id"])
                if len(set(holds)) == 2:
                    sabotage.status = "resolved"
                    sabotage.resolved_at = now
        else:
            value = sabotage.repairs.get(panel["id"], {})
            require(
                value.get("player_id") == str(state.player_id),
                "FORBIDDEN",
                "Сначала начните ремонт",
            )
            require(
                (now - date(value["since"])).total_seconds() >= 2,
                "TOO_EARLY",
                "Ремонт ещё не завершён",
            )
            require(
                sabotage.kind != "reactor",
                "FORBIDDEN",
                "Удерживайте оба терминала одновременно",
            )
            require(
                isinstance(payload.get("solution"), list)
                and all(type(v) is int for v in payload["solution"])
                and payload["solution"] == sabotage.challenge[panel["id"]],
                "BAD_SOLUTION",
                "Неверная настройка",
            )
            value["done"] = True
            sabotage.repairs[panel["id"]] = value
            if all(v.get("done") for key, v in sabotage.repairs.items()) and (
                sabotage.kind != "oxygen"
                or len([v for v in sabotage.repairs.values() if v.get("done")]) >= 2
            ):
                sabotage.status = "resolved"
                sabotage.resolved_at = now
        sabotage.save(update_fields=["repairs", "status", "resolved_at"])
        return [
            {
                "type": (
                    "sabotage.resolved"
                    if sabotage.status == "resolved"
                    else "sabotage.updated"
                ),
                "kind": sabotage.kind,
            }
        ]


def handle_command(game, room, state, payload, now):
    require, near, uuid_value = rules()
    kind = payload["type"]
    events = []
    extra = kind.startswith(("vent.", "sabotage.", "meeting.chat.")) or kind in [
        "door.interact",
        "player.ability.use",
        "terminal.use",
    ]
    if not extra:
        return False, []
    require(
        kind
        in {
            "vent.enter",
            "vent.travel",
            "vent.exit",
            "sabotage.start",
            "sabotage.repair.begin",
            "sabotage.repair.complete",
            "meeting.chat.send",
            "door.interact",
            "player.ability.use",
            "terminal.use",
        },
        "BAD_PAYLOAD",
        "Unknown command",
    )
    if kind == "meeting.chat.send":
        require(
            game.phase == "meeting", "INVALID_PHASE", "Чат доступен только на собрании"
        )
        meeting = game.meetings.filter(finished_at__isnull=True).first()
        require(
            meeting and not meeting.result_ends_at,
            "INVALID_PHASE",
            "Обсуждение завершено",
        )
        text = payload.get("text")
        require(
            isinstance(text, str)
            and 1 <= len(text.strip()) <= 500
            and "\x00" not in text,
            "BAD_PAYLOAD",
            "Сообщение: 1–500 символов",
        )
        last = (
            meeting.messages.filter(player_id=state.player_id)
            .order_by("-created_at")
            .first()
        )
        require(
            last is None or (now - last.created_at).total_seconds() >= 1,
            "RATE_LIMITED",
            "Подождите секунду",
        )
        require(
            meeting.messages.count() < 200, "RATE_LIMITED", "Лимит сообщений встречи"
        )
        message = MeetingMessage.objects.create(
            meeting=meeting,
            player_id=state.player_id,
            text=text.strip(),
            ghost_channel=not state.alive,
        )
        message.created_at = now
        message.save(update_fields=["created_at"])
        return True, [{"type": "meeting.chat.message"}]
    require(game.phase == "playing", "INVALID_PHASE", "Дождитесь конца собрания")
    if not kind.startswith("vent."):
        require(not state.is_in_vent, "FORBIDDEN", "Сначала выйдите из тоннеля")
    if kind.startswith("vent."):
        require(state.alive and game.settings.get("vents", True))
        require(state.role == "impostor" or state.special_role == "technician")
        require(
            state.vent_available_at is None or now >= state.vent_available_at,
            "COOLDOWN",
            "Тоннель временно недоступен",
        )
        nodes = game_map(game)["vents"]
        node = next((v for v in nodes if v["id"] == payload.get("vent_id")), None)
        if kind == "vent.enter":
            require(
                not state.is_in_vent and node and node["room_id"] in active_rooms(game)
            )
            require(near(state, node, 75), "OUT_OF_RANGE", "Подойдите к люку")
            state.is_in_vent = True
            state.observing = ""
            game.tasks.filter(player_id=state.player_id, is_completed=False).update(
                started_at=None, challenge=[]
            )
            state.current_vent_id = node["id"]
            state.direction_x = state.direction_y = 0
            state.vent_transition_started_at = now
            if state.special_role == "technician":
                state.ability_state = {
                    **state.ability_state,
                    "vent_deadline": iso(now + timedelta(seconds=20)),
                }
            record_effect(game, "vent.entered", state, now)
        elif kind == "vent.travel":
            current = next((v for v in nodes if v["id"] == state.current_vent_id), None)
            require(
                state.is_in_vent
                and current
                and node
                and node["id"] in current["connected_vent_ids"]
                and node["room_id"] in active_rooms(game),
                "FORBIDDEN",
                "Этот тоннель не соединён с текущим",
            )
            state.current_vent_id = node["id"]
            state.x = node["x"]
            state.y = node["y"]
            state.vent_transition_started_at = now
        elif kind == "vent.exit":
            require(state.is_in_vent)
            node = next(v for v in nodes if v["id"] == state.current_vent_id)
            require(
                not blocked(
                    node["x"], node["y"], game_map(game), closed_doors(game, now)
                ),
                "OCCUPIED",
                "Выход занят",
            )
            state.x, state.y = node["x"], node["y"]
            state.is_in_vent = False
            state.current_vent_id = ""
            record_effect(game, "vent.exited", state, now)
        else:
            require(False, "BAD_PAYLOAD", "Неизвестная команда люка")
        state.vent_available_at = now + timedelta(
            seconds=(
                30 if kind == "vent.exit" and state.special_role == "technician" else 1
            )
        )
        state.save()
        return True, [{"type": "vent.state"}]
    if kind.startswith("sabotage."):
        return True, (
            SabotageManager.start(game, state, payload, now)
            if kind == "sabotage.start"
            else SabotageManager.repair(game, state, payload, now)
        )
    require(not state.is_in_vent)
    if kind == "door.interact":
        require(state.alive)
        door = next(
            (d for d in game_map(game)["doors"] if d["id"] == payload.get("door_id")),
            None,
        )
        require(door and (game.map_mode == "full" or door["compact"]))
        r = door["bounds"]
        require(
            near(
                state,
                {"x": r["x"] + r["width"] / 2, "y": r["y"] + r["height"] / 2},
                110,
            ),
            "OUT_OF_RANGE",
            "Подойдите к шлюзу",
        )
        require(
            not game.doors.filter(door_id=door["id"], closed_until__gt=now).exists(),
            "COOLDOWN",
            "Шлюз заблокирован до окончания таймера",
        )
        require(
            not any(
                blocked(
                    p.x,
                    p.y,
                    {"width": 6144, "height": 4096, "player_hitbox": 28, "walls": []},
                    [r],
                )
                for p in game.player_states.filter(alive=True, is_in_vent=False)
            ),
            "OCCUPIED",
            "Проход занят",
        )
        DoorState.objects.update_or_create(
            game=game,
            door_id=door["id"],
            defaults={"closed_until": now + timedelta(seconds=2)},
        )
        return True, [{"type": "door.state"}]
    if kind == "terminal.use":
        require(state.alive)
        if payload.get("terminal_id") == "":
            state.observing = ""
            state.save(update_fields=["observing"])
            return True, []
        terminal = next(
            (
                t
                for t in game_map(game)["terminals"]
                if t["id"] == payload.get("terminal_id")
            ),
            None,
        )
        require(
            terminal and near(state, terminal, 100),
            "OUT_OF_RANGE",
            "Подойдите к терминалу",
        )
        require(
            not game.sabotages.filter(
                kind="comms", status__in=["active", "repairing"]
            ).exists(),
            "FORBIDDEN",
            "Связь отключена",
        )
        if terminal["type"] == "vitals":
            require(
                not game.settings.get("special_roles") or state.special_role == "medic"
            )
        if payload.get("camera_id"):
            require(
                payload["camera_id"] in [c["id"] for c in game_map(game)["cameras"]],
                "BAD_PAYLOAD",
                "Нет такой камеры",
            )
            state.ability_state = {
                **state.ability_state,
                "camera": payload["camera_id"],
            }
        state.observing = terminal["id"]
        state.direction_x = state.direction_y = 0
        state.save()
        return True, [{"type": "ability.result"}]
    if kind == "player.ability.use":
        require(game.settings.get("special_roles"))
        require(
            state.ability_available_at is None or now >= state.ability_available_at,
            "COOLDOWN",
            "Способность перезаряжается",
        )
        target = game.player_states.filter(
            player_id=uuid_value(payload.get("target_player_id")), alive=True
        ).first()
        require(target and target.player_id != state.player_id)
        if state.special_role == "tracker" and state.alive:
            state.ability_state = {
                **state.ability_state,
                "tracking": dict(
                    room_id=None if target.is_in_vent else room_at(game, target),
                    until=iso(now + timedelta(seconds=8)),
                ),
            }
            cooldown = 35
        elif state.special_role == "mimic" and state.alive and state.role == "impostor":
            state.ability_state = {
                **state.ability_state,
                "mimic_target": str(target.player_id),
                "mimic_until": iso(now + timedelta(seconds=12)),
                "appearance_epoch": str(uuid.uuid4()),
            }
            cooldown = 45
        elif not state.alive and state.role == "crew":
            require(
                state.ability_state.get("shields_used", 0) < 2,
                "ALREADY_DONE",
                "Защиты закончились",
            )
            target.ability_state = {
                **target.ability_state,
                "shield_until": iso(now + timedelta(seconds=10)),
            }
            target.save(update_fields=["ability_state"])
            state.ability_state = {
                **state.ability_state,
                "shields_used": state.ability_state.get("shields_used", 0) + 1,
            }
            cooldown = 30
        else:
            require(False)
        state.ability_available_at = now + timedelta(seconds=cooldown)
        state.save()
        return True, [{"type": "ability.result"}]
    return False, []


def advance_world(game, room, now):
    changed = False
    for sabotage in game.sabotages.filter(
        status__in=["active", "repairing"], deadline_at__lte=now
    ):
        sabotage.status = (
            "failed" if sabotage.kind in ["reactor", "oxygen"] else "resolved"
        )
        sabotage.resolved_at = now
        sabotage.save(update_fields=["status", "resolved_at"])
        changed = True
        if sabotage.status == "failed" and game.phase != "finished":
            game.phase = room.status = "finished"
            game.winner = "impostor"
            game.finish_reason = sabotage.kind + "_timeout"
            game.finished_at = now
            room.save(update_fields=["status"])
            game.player_states.update(direction_x=0, direction_y=0)
    if game.doors.filter(closed_until__lte=now).exists():
        game.doors.filter(closed_until__lte=now).delete()
        changed = True
    for state in game.player_states.all():
        if (
            state.special_role == "technician"
            and state.is_in_vent
            and not future(state.ability_state.get("vent_deadline"), now)
        ):
            state.is_in_vent = False
            state.current_vent_id = ""
            state.vent_available_at = now + timedelta(seconds=30)
            state.save()
            changed = True
        if state.ability_state.get("mimic_until") and not future(
            state.ability_state["mimic_until"], now
        ):
            state.ability_state = {
                k: v
                for k, v in state.ability_state.items()
                if k not in ["mimic_until", "mimic_target"]
            }
            state.ability_state["appearance_epoch"] = str(uuid.uuid4())
            state.save(update_fields=["ability_state"])
            changed = True
    return changed
