# Crew Mission — Backend

Original multiplayer 2D social-deduction game. Backend foundation: **Django 5.2 LTS, Django REST Framework, Django Channels, PostgreSQL, Redis**. Local development can use SQLite and the in-memory Channel Layer; production **must** use PostgreSQL and Redis.

## Quick start

1. Install Python 3.12+ and create a virtual environment.
2. `pip install -r requirements.txt`
3. `cp .env.example .env` (on Windows, copy manually); change `DJANGO_SECRET_KEY` when deploying.
4. `python manage.py migrate`
5. `python manage.py runserver 0.0.0.0:8000` — Channels/Daphne ASGI serves HTTP + WS.
6. Health: `GET http://localhost:8000/api/v1/health/`.
7. Tests: `python manage.py test`; system check: `python manage.py check`.

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

**Project status:** stage A match models, start and secret roles are implemented. Movement, tasks, kills, meetings, voting and win evaluation remain future stages. See [stage A setup and verification](docs/STAGE-A.md) and [WebSocket events](docs/WS-EVENTS.md).
