# CREW MISSION 2.0 — implementation ledger

Publication is deferred at the user's request. Work stays on `ai/backend-v2`; no main merge or production change is authorized without the review required by the specification.

## Baseline audit

The updated backend main was audited at `6d89208` (previous gameplay work merged). The existing 69 backend tests passed against local PostgreSQL and Redis before v2 changes. Existing Room DTOs, Guest authentication, transactional Room → Game lock ordering, Channels and the durable clock are extended, not replaced. Frontend counterpart: `ai/frontend-v2`, baseline `2cf2e19`.

## Implemented

- Immutable map binding on GameSession: old rows default to map v1; new rooms default to Asterion v2. The original map is preserved byte-for-byte.
- Asterion 6144×4096, 21 rooms, 40 stations, 20 reciprocal vent nodes in three networks, compact/full layouts, doors, colliders, terminals, emergency panels, camera definitions and navigation metadata.
- Server-owned settings and unique lobby color selection; immutable match settings captured on start.
- 20 challenge-specific validators, category assignment (default 1 common + 4 short + 2 long), multi-stage tasks and ghost obligations.
- Locked vent transitions, cooldowns, proximity/link/role validation; private tunnel position, nearby visible entrance/exit effects.
- Five sabotage types, durable deadlines, shared cooldown, two simultaneous reactor holds, two oxygen codes, repair validation and physical door locks. Report cancels reactor/oxygen; emergency calls are blocked during critical incidents.
- Observer-filtered snapshots with distance and wall/door LOS. Redis room groups carry only state-version invalidations. Observer events are built from filtered views; task challenges are sent only to their owner. Protocol v1 clients receive UPGRADE_REQUIRED for v2 matches.
- Authorized admin/camera/vitals terminal views; comms disables observations and hides assignments until repair.
- Living/ghost meeting chat isolation, rate and length limits, voting settings, optional ejection confirmation, absolute result-presentation deadline.
- Optional technician, medic, tracker, guardian and mimic abilities (off by default).
- Clock skips abandoned idle rooms, while meetings, critical deadlines and technician vent expiry still advance without browsers.

## Evidence obtained

- Baseline: 69 backend tests passed.
- Current checkpoint: `python manage.py test --noinput` — **91 tests passed**, PostgreSQL + Redis, including real PostgreSQL concurrent critical sabotage and actual Channels socket privacy checks.
- `python scripts/check_map.py` — both v1 and Asterion match frontend byte-for-byte; legacy file unchanged.
- `python -m scripts.check_asterion` — full: 5,656 reachable cells / 67 goals / 21 rooms; compact: 2,520 cells / 31 goals / 9 rooms.
- Paired frontend has passed 20 real task-panel submissions through WebSocket to these Django validators. The panel suite explicitly seeds its disposable local test assignments; it does not mock requests or replace the server.
- Four- and ten-browser map/reconnect/chat checks passed. A subsequent four-browser scenario completed a real task and ended with a crew voting victory.

## Verification still in progress

- Full real-browser vent → repair → door collision → kill → ghost task → report → vote/parity flow after the latest input/clock changes.
- Real crew task victory and critical timeout; multi-room load, reconnect and worker restart measurement.
- Final frontend/browser regression, protocol documentation, CI and pull request review.
- Optional-role multiplayer balancing and physical iOS hardware remain distinct from desktop WebKit checks; do not claim physical-device results.

## Local continuation

Python: `venv/bin/python` (3.12). Database: PostgreSQL on 55432, Redis on 56379. Use local-only development environment variables; never commit `.env` or guest tokens. Run migrations, then Daphne on 8000 and `manage.py run_game_worker`. Frontend serves on 3000; `/demo/asterion` explores the map without a match. Real matches need four independent guest sessions.

Historical v1 reports in the workspace are not evidence of v2 acceptance. Update this ledger with measured results; do not mark unrun checks as passed.
