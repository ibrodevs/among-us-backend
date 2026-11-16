# Production runbook

Deployment is not completed. Owner must supply an approved backend server and domain, frontend Vercel project/domain, real secrets through the hosting environment, and a reviewer must approve the PRs. No new paid service, DNS or production secret has been created or changed.

## Backend

Requires Python 3.12, PostgreSQL 16, Redis and **two service types**: Daphne HTTP/WebSocket and `python manage.py run_game_worker`. Django runserver is development only. The worker is mandatory: it advances meetings even if all browsers disconnect. PostgreSQL Room locks + `last_tick_at` prevent duplicate simulation steps across workers; initially run one clock worker per deployment. Redis transports events across the API and clock processes.

1. Review and merge the migrations; record previous immutable image/commit.
2. Create `.env` on the server using `.env.example`. Set `DJANGO_DEBUG=false`, a unique random `DJANGO_SECRET_KEY` of at least 50 characters, explicit `DJANGO_ALLOWED_HOSTS`, exact `CORS_ALLOWED_ORIGINS`, and `POSTGRES_PASSWORD`. Never commit `.env`. Use a URL-safe password for the Compose connection string.
3. `docker compose build`
4. `docker compose up -d db redis`
5. `docker compose run --rm api python manage.py migrate --noinput`
6. `docker compose run --rm api python manage.py check --deploy`
7. `docker compose up -d api worker`
8. Configure the provided Caddy example with the approved hostname and TLS. Caddy reverse-proxies `/api/` and `/ws/`, including WebSocket upgrade, and overwrites forwarding headers. Set `TRUST_PROXY_HTTPS=true` **only** behind that proxy. Do not expose port 8000 or database/Redis ports publicly.
9. Verify HTTPS health, a real WSS auth and reconnect, CORS from the frontend domain, and a complete 4-player game through the actual public URLs. Check logs for both API and worker.

The provided Docker/Compose configurations are prepared but were not executed here (no Docker runtime). They need a deployment smoke test on the selected server. Compose pins major service lines; use immutable image digests under your release policy before a production rollout.

## Frontend / Vercel

Import `ibrodevs/among-us-frontend` with the Next.js preset, Node 22, `npm ci`, `npm run build`. Set `NEXT_PUBLIC_API_URL=https://<approved-backend>` and `NEXT_PUBLIC_WS_URL=wss://<approved-backend>` **before building**. Browser-facing variables are public and must never contain secrets. Preview origins must be explicitly added to backend CORS/WS allowed origins. Test previews before promoting; no production promotion before review and green CI.

## Backups and rollback

Before migration, back up PostgreSQL with `pg_dump -Fc` to protected off-server storage; do not put database dumps in Git. Back up daily and test restore into a separate database using `pg_restore --clean --if-exists --no-owner`. A backup is not accepted until the restored database passes Django checks and a match/reconnect smoke test.

Rollback: stop API and clock, restore the prior image/commit and compatible DB backup, then restart both services and verify health/WSS. Do not blindly reverse migrations or reuse a newer schema with an incompatible binary. Redis is transport; it is not the durable match backup. Add alerting for worker downtime, DB failures and recurring WebSocket service errors. Health is a liveness endpoint; readiness separately runs `SELECT 1` and Redis `PING` in deployment checks.

No public URL or performance SLA is asserted until measured on the selected infrastructure.
