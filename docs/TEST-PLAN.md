# Integration and QA gates

## Bootstrap commands
`python manage.py check`
`python manage.py makemigrations --check --dry-run`
`python manage.py migrate`
`python manage.py test`

## Kutman REST acceptance
- POST guests creates signed id; invalid nickname rejected.
- With Guest header, create room and join from 3 other guest identities.
- Wrong/expired signature 401. Non-member cannot read the room.
- Full/started rooms reject join with 409; duplicate join is safe.
- Transfer host after leaving, destroy empty lobby.
- Run tests on PostgreSQL to validate row locking (SQLite does not test select_for_update).

## Iliyar game acceptance
- Host starts at 4; non-host and room<4 forbidden.
- All participants receive personal role safely; public events have no hidden roles.
- Observe movement, tasks, a kill, report and vote in 4 browser windows.
- Server rejects movement through wall, too-fast move, repeat voting, out-of-range kill.
- Crew and impostor wins, reconnect and concurrent votes.
- Observe that timeouts advance with server time and not on trusting client time.

Current game endpoints are deliberate placeholders; the game checks remain pending work until Iliyar completes them.
