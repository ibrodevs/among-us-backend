# Backend architecture and contract

## Ownership
- `players/`: guest identity, signed token and validation — Kutman.
- `rooms/`: room membership, host, lobby state, code generation and database constraints — Kutman.
- `game/`: WebSocket protocol, authoritative state machine, role assignment, tasks, meetings, voting and win conditions — Iliyar.
- `config/`: shared; changes need explicit coordination.

Django REST Framework handles guest/room operations and game start. Django Channels (ASGI) handles room WebSocket events. PostgreSQL is production database; Redis Channel Layer shares events across processes. SQLite/InMemory Channel Layer are for local one-process development only.

## Security invariants
- Every REST and WS action is bound to the authenticated signed guest ID, never a caller-provided `player_id`.
- Host-only game start, min 4 players. No joining started rooms.
- Group messages contain only PUBLIC state; private role/task assignment is sent to the authenticated socket only.
- Every gameplay action is validated on the server: role, phase, distance, cooldown, alive status, vote uniqueness, idempotent tasks.
- Game result derives from server state; not client claims.
- Disconnection/reconnection and concurrent votes/kills are controlled with DB transactions or equivalent deterministic serialization.
- Log enough for debugging without logging guest tokens, hidden roles and personal identifiers unnecessarily.

## Current bootstrap vs future work
Bootstrap has working guest/room REST endpoints, signed auth, explicit 501 game-start placeholder, WebSocket auth handshake and snapshot. Iliyar must implement all gameplay actions and lobby push events. Kutman must harden lobby concurrency, permissions and tests before production. The frontend `docs/API-CONTRACT.md` is authoritative for the event envelope and endpoint names.

## Deployment checklist (future)
Production `DJANGO_DEBUG=false`, strong `DJANGO_SECRET_KEY`, strict host/origin allow lists, PostgreSQL DATABASE_URL, Redis REDIS_URL, ASGI server, WSS/TLS at proxy, static files, health checks, logs, DB backups, WebSocket load test. Do not serve production game with InMemoryChannelLayer.


## Implemented integration extension
See [WebSocket v1](WS-EVENTS.md) for the actual typed snapshots, private state, clock worker, shared geometry and departure rules. PostgreSQL is authoritative; Redis delivers committed events. The frontend route `/game/{code}` runs the real match; `/demo` is the isolated local physics demo. No demo crew are used in live matches. Release review and deployment verification remain separate gates.

PostgreSQL uses the Django/psycopg bounded native connection pool (2–16 connections per process) with CONN_MAX_AGE=0 for ASGI. This removes connection setup churn observed under ten-client input traffic; idle clients also stop resending unchanged zero directions. Pool configuration follows [Django 5.2 database guidance](https://docs.djangoproject.com/en/5.2/ref/databases/#connection-pool). Total pool capacity must fit the database connection budget across API and clock replicas.
