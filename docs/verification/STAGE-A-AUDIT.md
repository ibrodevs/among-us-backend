# Stage A audit — 2026-11-16

Source refs fetched from GitHub: main fdbf1eb, Kutman 4a08929, Iliyar 7afbe1c. Both feature branches are preserved; local review candidate merges their histories. Only README conflicted; retained working room and start descriptions.

| Module | Existing implementation | Audit / verification |
|---|---|---|
| Guests/rooms | Kutman: validation, throttle, atomic capacity, host transfer, idempotent join | 48 combined tests pass on PostgreSQL 16, no skips |
| Match start | Iliyar: persisted random roles, transaction, private delivery | Start/room roster race tests pass on PostgreSQL |
| Lobby notifications | Kutman signal had no receiver | Added post-commit channel notification receiver |
| Presence | Advisory boolean | Needs connection leases before production |
| Spawns/map | Backend central spawns and frontend walls disagree | Resolve in B using a versioned shared map JSON |
| Gameplay | Commands explicitly unimplemented | B/C work required |

Commands: `DJANGO_DEBUG=true DJANGO_SECRET_KEY=<local> DATABASE_URL=postgres://Apple@127.0.0.1:55432/crew_mission venv/bin/python manage.py test --verbosity 1` → 48 passed. `manage.py check` → no issues. `manage.py makemigrations --check --dry-run` → no changes. SQLite baseline also passed with 4 lock tests skipped; PostgreSQL supersedes that result.

Stage A is not accepted by teammates yet. Human review, frontend integrated browser verification and GitHub CI remain separate gates. No changes to main or personal branches.
