# HQLookup production deployment

This repository contains a FastAPI API and a Next.js frontend. Production is
designed around one public frontend origin. Browser requests use `/backend/*`;
Next.js rewrites that path to the private `BACKEND_URL`. This keeps the
HttpOnly session cookie same-origin and avoids exposing the backend URL in the
client bundle.

## Release order

1. Copy only the variable names from `.env.example` and
   `frontend/.env.example` into the deployment platform's secret manager.
   Never upload the local `.env` file.
2. Set `APP_ENV=production`, `PUBLIC_SIGNUP_ENABLED=false`, HTTPS origins, a TLS PostgreSQL URL, a TLS Redis
   URL, exact trusted hosts, live Stripe values, and a newly generated JWT key.
   Production also requires `EMBEDDING_MODEL_PATH` to point at a vetted local
   safetensors model baked into the image; it must not download model files at
   request time.
   Provision the first owner through a controlled database/bootstrap procedure,
   then use workspace invitations for additional accounts.
3. Build the frontend with its server-only `BACKEND_URL` set to the reachable
   API origin.
4. Run `alembic upgrade head` as a one-off release command.
5. Start the API with `make start` and the frontend with `npm start`.
6. Configure Stripe to call `/backend/billing/webhook` on the public frontend
   origin (or `/billing/webhook` when the API has its own public origin), and
   keep the webhook secret in the API secret manager.

The security migration revokes legacy invitation links and permanently clears
their plaintext bearer tokens. Send fresh invitations after the migration.
If duplicate `(org_id, user_id)` membership rows exist, migration intentionally
stops so they can be reconciled before the uniqueness constraint is added.
It also stops on case-folded duplicate emails or duplicate Stripe customer /
subscription IDs. Take a database backup, verify `alembic current`, and run
`alembic check` against the actual target schema before applying the release;
legacy databases created outside the migration chain need an explicit schema
baseline/reconciliation first.

`TRUSTED_HOSTS` must contain every host the API actually receives through the
rewrite (commonly the public app host and/or the private API service host).
Set `FORWARDED_ALLOW_IPS` to the exact reverse-proxy addresses or CIDRs so login
rate limits use the real client address; never set it to `*` on a public API.

Production validation intentionally refuses placeholder secrets, localhost,
non-HTTPS browser/LLM URLs, non-TLS Redis, database URLs without `sslmode`,
insecure cookies, and missing billing/email configuration.

Uploaded document content and questions are sent to the configured LLM
endpoint. Query history is stored in PostgreSQL and active search context is
cached in Redis for up to six hours. Configure provider retention, database and
Redis encryption, backups, log access, and deletion policies to match your data
handling requirements.

## Required release gates

Run before every deployment:

```bash
python -m pytest -q
pip-audit -r requirements.txt
cd frontend
npm ci
npm audit --audit-level=high
npm run lint
npx tsc --noEmit --incremental false
npm run build -- --webpack
```

The GitHub Actions workflow runs these checks and applies the complete
migration chain to a fresh pgvector-enabled PostgreSQL database.

## Secret rotation

The historical repository contained a PostgreSQL credential. Rotate it before
using this code in any shared or production environment. If an earlier build
logged session cookies, rotate `JWT_SECRET_KEY` as well; that invalidates those
sessions. History rewriting is optional after rotation and depends on how the
repository has been shared. Remove or reset any legacy seeded accounts before
production; the old seed data included predictable development identities.
