# Crew Mission — Backend

Original multiplayer 2D social-deduction game. Backend foundation: **Django 5.2 LTS, Django REST Framework, Django Channels, PostgreSQL, Redis**. Local development can use SQLite and the in-memory Channel Layer; production **must** use PostgreSQL and Redis.

## Quick start — full multiplayer match

1. Install Python 3.12+, PostgreSQL and Redis; create a virtual environment.
2. `pip install -r requirements.lock.txt`
3. Copy `.env.example` to `.env`. For the **full game**, set `DATABASE_URL` to your PostgreSQL database and `REDIS_URL` to your Redis instance. Set a local development key; use a separate strong secret for production.
4. `python manage.py migrate --noinput`
5. Start the API: `daphne -b 127.0.0.1 -p 8000 config.asgi:application`.
6. In a second terminal, with the same virtualenv/environment, start `python manage.py run_game_worker`.
7. Start the sibling frontend following its README; open http://localhost:3000 in four separate browser profiles and create/join a room.
8. Health: `GET http://localhost:8000/api/v1/health/`.
9. Verification: `python manage.py test`, `python manage.py check`, `python manage.py makemigrations --check --dry-run`.

The clock process is mandatory for movement and timers. SQLite plus the in-memory channel layer can exercise isolated Stage A/API tests, but **cannot deliver full match events across separate API/clock processes**. Use PostgreSQL and Redis for complete integration. Docker/Compose instructions are in [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Endpoints / architecture
- `POST /api/v1/guests/` — create signed 24-hour guest identity.
- `POST /api/v1/rooms/`, `POST /api/v1/rooms/join/`, `GET /api/v1/rooms/<code>/`, `POST /api/v1/rooms/<code>/leave/` — guest-authenticated lobby with atomic capacity checks, idempotent joins, host transfer and cleanup. Guest creation is limited to 10 requests/minute per peer IP per cache.
- `POST /api/v1/games/<code>/start/` — host-only atomic start for 4–10 members; returns the public Room DTO.
- `ws(s)://host/ws/rooms/<code>/` — guest authentication, public room snapshots and private persisted role delivery, including reconnect.
- `GET /api/v1/health/` — service health.

## Team ownership
- Kutman — branch `feature/kutman-rooms-api`: `players/`, `rooms/`, room REST/database/security
- Iliyar — branch `feature/iliyar-game-engine`: `game/`, WebSocket/events/match state/rules/tests
- Shared: `config/` and cross-app model interfaces only with coordinated review.

`rooms.signals.lobby_changed` sends `room_code` after a successful join or leave commits. A receiver should reload the public lobby state and handle a missing room after the last departure.

Read the API contract in the frontend repository `docs/API-CONTRACT.md` and the backend `docs/ARCHITECTURE.md` before implementing features. Start from `main`, push only to your own feature branch and open a PR after tests/review. No PRs are pre-opened.

**Project status:** stage A match models, start and secret roles are implemented. Movement, tasks, kills, meetings, voting and win evaluation are implemented in the separate gameplay review candidate. See [stage A setup and verification](docs/STAGE-A.md) and [WebSocket events](docs/WS-EVENTS.md).


## Full game runtime
Install `requirements.lock.txt` for reproducible versions. Apply migrations, then run Daphne **and** `python manage.py run_game_worker` with the same PostgreSQL DATABASE_URL and Redis REDIS_URL. Without the clock there is no authoritative movement or automatic phase advancement. See [protocol](docs/WS-EVENTS.md), [deployment/rollback](docs/DEPLOYMENT.md), and verification reports in `docs/verification/`. Production requires PostgreSQL, Redis, an explicit strong key and exact CORS/WS origins.

The optional `scripts/smoke_stack.py` checks a disposable running stack using real HTTP and WebSocket messages (`pip install 'websockets>=15,<17'`). CI runs it against the actual Docker/Compose images in the `container-smoke` job and cleans up its test memberships.
