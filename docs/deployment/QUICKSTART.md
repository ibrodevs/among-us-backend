# Deploy CREWMATE X yourself

1. Backend Docker image from `main` → Northflank Sandbox.
2. Supply the shared secrets listed in `.env.example` and `NORTHFLANK.md`; PostgreSQL must be a direct/session TLS endpoint, Redis must support the native protocol.
3. Run a one-off container with `SERVICE_ROLE=migrate`.
4. Start API (`SERVICE_ROLE=api`, public port 8000) and clock (`SERVICE_ROLE=worker`, no public port). Use the documented health checks.
5. Vercel Hobby frontend from `main`: set `NEXT_PUBLIC_API_URL=https://BACKEND` and `NEXT_PUBLIC_WS_URL=wss://BACKEND`, then build. Put its exact HTTPS origin in backend CORS.
6. Check the readiness URL and a real 20-player match with host-selected impostor count.

No paid resources or deployments have been created by the agent. Confirm your account's Sandbox/Free quota before provisioning. Detailed settings, sources, resource estimate and limitations: [NORTHFLANK.md](NORTHFLANK.md).
