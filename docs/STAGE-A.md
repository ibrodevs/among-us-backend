# Stage A — match start and secret roles

Implemented from `TZ_Stage_A_Iliyar_Backend.docx` in `feature/iliyar-game-engine`. This stage-specific assignment takes precedence over the broader B/C roadmap in `TZ-ILIYAR-BACKEND.md` and `TEST-PLAN.md`.

## Implementation

- `game/models.py` and tracked `game/migrations/0001_initial.py`: one `GameSession` per room; unique `PlayerGameState` per game/player; durable roles, spawns, sequence and cooldown fields; assignments and minimal corpse/meeting/vote schemas with DB uniqueness constraints.
- `game/services/start.py`: one transaction with a Room row lock, current host/membership/status/capacity checks, fixed roster including offline members, server role assignment, saved spawns, and public Room response.
- `game/services/roles.py`: `secrets.SystemRandom` sampling, 1 impostor for 4–6 players and 2 for 7–10. Ten distinct central spawn points on the 1600×900 map; future collision geometry must preserve this spawn area.
- `game/services/events.py`, `snapshots.py` and consumer: public room group, authenticated player groups, owner-only DB reads and reconnect replay. Notifications run after commit.
- `TaskAssignment`, `Corpse`, `Meeting`, `Vote` are schema only. Assignments start empty. Movement, kill, task completion, voting, timers and winners are not implemented in this stage.

No `rooms/`, `players/` or `config/` files or existing migrations were changed. The original Room DTO is preserved. Start, join and leave use the same existing Room locking convention. The frontend contract was read; concrete integration examples are in [WS-EVENTS.md](WS-EVENTS.md). Frontend teammate acceptance is a separate human review.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Set a private DJANGO_SECRET_KEY in .env.
# Set DATABASE_URL to a PostgreSQL database and REDIS_URL to Redis.
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Use PostgreSQL and Redis to exercise real row locks and communication across workers. The repository's SQLite/in-memory defaults remain available for quick local development; SQLite skips the three row-lock concurrency tests.

```sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test --verbosity 2
.venv/bin/python -m pip check
```

`POST /api/v1/games/{code}/start/` accepts `Authorization: Guest <token>` and returns `200` public Room with `status=playing`. No body fields influence roles. Missing/invalid auth → `401`; missing room → `404`; non-member/non-host → `403`; insufficient players, invalid status, existing game or over-capacity roster → `409`. For 1–3 members the exact detail is `At least 4 players required`.

## Acceptance coverage

| Assignment checks | Automated coverage |
| --- | --- |
| E01–E04 | Missing/invalid auth, outsider, non-host, host without membership, 1–3 participants |
| E05–E06 | Every size from 4 through 10; exact role counts, saved spawns, alive states and no premature finish |
| E07–E08 | Repeat start preserves roles; PostgreSQL parallel requests produce exactly one success and one conflict |
| E09 | REST response, room detail and RoomSerializer field allowlists |
| E10–E12 | Four authenticated sockets, public group interception, separate private recipients, owner-only role/task delivery |
| E13 | Invalid/expired tokens, non-member, nonexistent room, first-frame auth and timeout |
| E14 | Offline start and reconnect preserve the game and own role; another player's tasks stay hidden |
| E15 | Django checks, migration drift check, new DB migration, full suite and dependency check |
| E16 | Offline members included; concurrent joins/leaves cannot change the start roster |
| Failure handling | DB rollback after states are inserted; failed Redis delivery preserves committed state; safe WS service errors |
| Additional security | Reauth cannot switch identity, membership rechecked before delivery, JSON/frame validation, auth/start race |

See [verification results](stage-a/verification.txt) and the [local demonstration](stage-a/demo.png).

## Live demonstration

Use a disposable development database: the demo creates four guests and a started room. Install the optional demo client and start the ASGI server first:

```sh
.venv/bin/python -m pip install websockets
.venv/bin/python -m game.demo_stage_a --url http://127.0.0.1:8000
```

The saved evidence was recorded using PostgreSQL 16, Redis 8.10.3 and two separate Daphne processes. HTTP start ran on port 18000; the four sockets connected to port 18001, proving Redis delivery across processes:

```sh
# Separate terminals with the same PostgreSQL DATABASE_URL and Redis REDIS_URL:
.venv/bin/daphne -b 127.0.0.1 -p 18000 config.asgi:application
.venv/bin/daphne -b 127.0.0.1 -p 18001 config.asgi:application
.venv/bin/python -m game.demo_stage_a --url http://127.0.0.1:18000 --ws-url http://127.0.0.1:18001 --output docs/stage-a/demo.json
```

The demo asserts REST `401/403/409/200`, four authenticated private events, the correct role count, public payload secrecy, repeat-start conflict and identical own state on reconnect. Its JSON omits tokens. `stage-a/demo.html` and `demo.png` display the recorded responses; they are evidence viewers, not the game frontend. The recorded disposable identities were removed after capture.
