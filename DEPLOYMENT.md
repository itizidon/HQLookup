# Deployment guide

The repository contains two deployable services:

- `app`: FastAPI, backed by PostgreSQL/pgvector and Redis.
- `frontend`: Next.js, which proxies browser `/api` requests to the FastAPI
  service through the server-only `API_ORIGIN` variable.

Keeping browser traffic on the frontend origin makes the host-only JWT cookie
work consistently and avoids exposing the internal backend address.

## Required services

Provision these before deploying:

1. PostgreSQL with permission to enable the `vector` extension.
2. Redis, preferably a TLS (`rediss://`) managed instance in production.
3. An OpenAI-compatible LLM endpoint and API key.
4. Stripe and Resend accounts if billing and invitation email are enabled.

## Configure environments

Copy `.env.example` locally and configure the equivalent variables in each
deployment service. Never upload `.env` itself.

Backend variables include `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, LLM,
Stripe, Resend, CORS, and cookie settings. Set `APP_ENV=production`, use a new
random JWT secret, enable secure cookies, and use TLS URLs in production.

Frontend variables:

- `API_ORIGIN`: private/reachable backend origin used only by the Next server,
  such as `http://backend:8000` on an internal network.
- `NEXT_PUBLIC_API_URL=/api`: public build-time browser path. Values prefixed
  with `NEXT_PUBLIC_` are visible to everyone and must never contain secrets.

Set `FRONTEND_URL` and `CORS_ALLOWED_ORIGINS` to the final HTTPS frontend
origin. Configure `JWT_COOKIE_DOMAIN` only if intentionally sharing auth across
trusted subdomains; otherwise leave it blank for a host-only cookie.

## Database release

For a new database, run this exactly once as the release/pre-deploy command:

```sh
python -m alembic upgrade head
```

Do not run `Base.metadata.create_all()` or the destructive seed/reset scripts
in production. Review `alembic/README` before deploying over a database created
before the baseline migration was repaired.

## Start the services

The root `Dockerfile` and `Procfile` run the backend on the platform-provided
`PORT`. The equivalent command is:

```sh
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

Deploy `frontend` with a Node 22-compatible Next.js host. Install with `npm ci`,
build with `npm run build`, and start with `npm run start`.

## External configuration

- Point the Stripe webhook at `https://<backend-or-proxied-host>/billing/webhook`
  and subscribe it to the events handled in `app/routes/billing.py`.
- Verify the Resend sender in `RESEND_FROM_EMAIL`.
- Restrict database and Redis network access to the backend service.
- Terminate TLS at the platform/load balancer and redirect HTTP to HTTPS.

## Release verification

Before promoting a release:

1. Confirm CI passes.
2. Back up an existing production database.
3. Apply migrations in staging, then production.
4. Check `/health/live` and `/health/ready`.
5. Register, sign in/out, and verify cookies are `Secure`, `HttpOnly`, and use
   the intended SameSite/domain policy.
6. Upload and query every supported file type (`pdf`, `docx`, `txt`, `md`,
   `csv`, `xlsx`, and `xls`).
7. Exercise invitation acceptance/revocation and tenant access boundaries.
8. Complete a Stripe test checkout and verify signed webhook handling.
9. Confirm logs contain no JWTs, document contents, prompts, or credentials.
10. Test database restore and rollback procedures before accepting traffic.
