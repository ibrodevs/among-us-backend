# CREWMATE X — self-deployment runbook

This prepares deployment; no cloud resources have been created. Use Sandbox/Free only. Do not attach a paid plan or enable automatic paid overages.

## Free test topology (verified 2026-11-17)

- Vercel Hobby: frontend Next.js; link `ibrodevs/among-us-frontend`, branch `main`.
- Northflank Sandbox: one API service and one continuously running clock service, one Redis addon, plus one migration job. PostgreSQL lives in an external Supabase Free project.
- Initial candidate: API `nf-compute-20` (0.2 vCPU/512 MiB), clock `nf-compute-20`, Redis `nf-compute-10` (0.1 vCPU/256 MiB) with 1 GiB disk. One instance each. Current public API lists $0.008/h, $0.008/h and $0.004/h respectively: about $14.88 for 744 hours, plus storage/network, before Sandbox credits. Sandbox advertises up to $20/month, 2 services, 2 jobs and 1 addon. Confirm eligibility and the final zero-cost estimate in your account before creating anything. If the account cannot supply this configuration free, stop rather than accepting a paid upgrade.
- These sizes are an initial TEST configuration, not a guarantee of 20-player performance. Database round-trip time and the small shared CPU quotas must be measured after deployment. Keep all services in the closest matching region. Supabase egress/connection limits are separate; monitor them.

Sources: [Northflank pricing](https://northflank.com/pricing), [current compute plans](https://northflank.com/docs/v1/application/billing/resource-plans-and-quotas), [public plan API](https://api.northflank.com/v1/plans). The observed response is saved in northflank-plans.json.

## 1. PostgreSQL and Redis

Create/use your own Supabase Free project. Obtain the **direct** or **session pooler** connection string from Connect. Session pooling provides IPv4 support; do not use the transaction pooler: the clock and migration job hold PostgreSQL session advisory locks. Passwords must be URL encoded.

Use a URL with `sslmode=require` at minimum. For server identity verification, download the Supabase CA and mount it as a secret file, set `DATABASE_SSLROOTCERT` to the file path; the app then uses `verify-full`. API/clock/migration dedicated sessions share the same TLS policy. Never commit actual credentials.

Create one private Redis/Valkey addon within the free quota. Use its authenticated private URL for both services. Use `rediss://` with certificate validation for an external public Redis provider. No Redis HTTP/REST-only endpoint: Channels needs the Redis protocol.

[Supabase connections/TLS](https://supabase.com/docs/guides/database/connecting-to-postgres), [pool limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits).

## 2. Shared environment secrets

Create a Northflank secret group and attach it to API, worker and migration job:

```env
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<generate a fresh cryptographically random value of at least 64 characters>
DJANGO_ALLOWED_HOSTS=<exact API hostname without https://>,localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=https://<your-frontend>.vercel.app
DATABASE_URL=<Supabase direct/session PostgreSQL connection URI with sslmode=require>
DATABASE_REQUIRE_TLS=true
REDIS_URL=<private authenticated Redis URL>
TRUST_PROXY_HTTPS=true
DB_POOL_MIN=1
GAME_METRICS_ENABLED=true
```

`TRUST_PROXY_HTTPS=true` is for a trusted TLS ingress which overwrites `X-Forwarded-Proto`. Public endpoints must be HTTPS/WSS. Never use wildcard CORS/Origin allowlists. If your ingress does not guarantee that header, configure that first. Health/readiness endpoints are HTTP redirect-exempt and reveal no credentials.

## 3. Build and controlled migration

Link backend repository `ibrodevs/among-us-backend`, branch `main`, Dockerfile `/Dockerfile`. Build once; use the same image for API, worker and migration job. Docker collects backend admin static files at build time with no real secrets; WhiteNoise serves the collected assets.

Create a one-off job with `SERVICE_ROLE=migrate`. Its command is the image default `/app/scripts/container-entrypoint.sh`. It executes `python manage.py migrate_serialized` under an advisory lock. Run it and verify success BEFORE starting/releasing API and worker. Do not run migrations independently from every replica.

## 4. API service

Use the same image and shared secrets, plus:

```env
SERVICE_ROLE=api
PORT=8000
DB_POOL_MAX=8
```

Expose internal port 8000 as public HTTP with Northflank TLS. Configure HTTP readiness `/api/v1/ready/` and liveness `/api/v1/health/`; start-up allowance 30 seconds, interval 10 seconds. `/ready/` checks PostgreSQL and Redis. Reserve a 20-second termination grace period. Daphne receives SIGTERM directly through `exec` and closes applications within 15 seconds. The image supports the injected PORT variable.

## 5. Clock service

Use the same image and shared secrets, plus:

```env
SERVICE_ROLE=worker
DB_POOL_MAX=4
```

Keep it continuously running, one instance, no public port. Configure command healthcheck `python scripts/check_worker_health.py`, interval 10s/start-up allowance 30s, termination grace period 20s. A dedicated PostgreSQL session advisory lock elects one leader; additional workers remain standby. SIGTERM/SIGINT request a clean stop; session close releases the lock. Match deadlines and authoritative state remain in PostgreSQL after restarts.

Northflank supports command and HTTP checks: [health checks](https://northflank.com/docs/v1/application/observe/configure-health-checks).

## 6. Frontend on Vercel

Link the frontend repo on Hobby, branch main, Next.js defaults (`npm ci`, `npm run build`). Set these build-time variables, then rebuild:

```env
NEXT_PUBLIC_API_URL=https://<exact backend hostname>
NEXT_PUBLIC_WS_URL=wss://<exact backend hostname>
```

Leave `MAP_REVIEW_ENABLED` unset for a public deployment. The map-review route is development/test-only. Add the resulting exact Vercel origin to backend `CORS_ALLOWED_ORIGINS`; redeploy API. No guest token goes in WebSocket URLs.

## 7. Acceptance and rollback

Verify `/health/` and `/ready/`, create a 20-seat room, select 3 impostors and connect 20 signed guests. The 21st join must return `409` with `code=ROOM_FULL`. Check role privacy, 119 crew assignments, movement, tasks, vents, repairs, kills/report, all votes and reconnect.

Run the supplied real-stack probes against the actual HTTPS API. Review p95/p99 RTT, command time, 10 Hz clock metrics, CPU/RSS, SQL count and message sizes. Local evidence does not establish Northflank performance. If the chosen free resources miss targets, document the bottleneck and use fewer simultaneous rooms/players or a different explicitly free host; do not silently upgrade.

Before later schema changes, export a database backup. Keep the previous API/clock image for rollback and apply only migrations compatible with the old release. Do not roll back database migrations containing user data without a reviewed recovery plan.
