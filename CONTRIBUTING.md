# Backend team workflow
1. Never work directly on `main`. Kutman: `feature/kutman-rooms-api`. Iliyar: `feature/iliyar-game-engine`.
2. Kutman owns `players/` and `rooms/`. Iliyar owns `game/`. `config/` changes require coordination and review.
3. Run `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python manage.py test`. Track every model migration.
4. Never disclose impostor roles or private assignments in public room responses, room broadcasts or logs. Server validates player actions, identity, range, phase, cooldown and voting.
5. Guest signing secret must be private in production; no raw tokens in URLs or logs. Production needs PostgreSQL and Redis.
6. One PR per coherent feature, include tests, endpoints/events changed, migration summary and steps to reproduce.
7. No merges until a second team member reviews and green checks are recorded.
