# CREWMATE X — 20-player release

## Behavior

- One room supports 4–20 members (default capacity 20); a 21st join returns 409/ROOM_FULL. Row locks serialize joins/settings/start; disconnected members retain their seats.
- Host chooses 1, 2 or 3 impostors, default 2. Start requires 4, 7 or 10 players respectively. Capacity must permit the selected count, settings lock after start, other members cannot change them. Roles are cryptographically sampled and remain private until the established reveal rules.
- Both maps have 20 collision-checked spawns; Asterion provides 21 furnished rooms, 20 distinct appearances, full/compact geometry, tasks, vents, sabotages, meetings, voting and ghosts.
- V2 observer frames share database reads for one state version/100ms bucket. Each identity receives a separately filtered public/private pair. Private data never enters the Redis room bus. Frame cache is bounded to 32 versions.
- PostgreSQL is authoritative. Redis carries version invalidations. The separate 10 Hz clock uses a dedicated PostgreSQL session advisory lock so extra workers remain standby. SIGTERM releases the leader session.

## Validation

`backend-tests.txt` contains the current full Django suite, including atomic join contention, selected roles, 20 votes/spawns, reconnect privacy, shared-frame query reuse, leader handoff and readiness failure handling. Map reachability verifies 110 full-map and 62 compact-map goals.

The sibling frontend supplies `scripts/capacity-20.mjs` (real 20-client integration with browser screenshots) and `scripts/load-20.mjs` (1800-second active-bot soak). Their sanitized reports are in its `docs/capacity-20/`. No guest tokens or auth frames are committed.

These are local-stack measurements. Northflank resource limits, Internet latency and Supabase round trips require a separate post-deployment run; local results do not certify performance on a free cloud plan.

## Deployment

Follow [QUICKSTART](../deployment/QUICKSTART.md) and the [Northflank runbook](../deployment/NORTHFLANK.md). Run the serialized migration job before API/worker release. Frontend environment URLs are build-time values. No cloud deployment is performed by this release.
