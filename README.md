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
2. Set `APP_ENV=production`, HTTPS origins, a TLS PostgreSQL URL, a TLS Redis
   URL, exact trusted hosts, live Stripe values, a newly generated JWT key,
   and a hostname-bound Cloudflare Turnstile secret in
   `TURNSTILE_SECRET_KEY`. Generate and securely retain a unique
   `DATA_ENCRYPTION_KEY`; rotating it requires re-enrolling MFA users and
   draining or discarding outstanding encrypted email records first.
   Set `PUBLIC_SIGNUP_ENABLED=true` when customers should be able to create
   accounts from the public sign-up page; omit it or set it to `false` for an
   invitation-only deployment.
   Production also requires `EMBEDDING_MODEL_PATH` to point at a vetted local
   safetensors model baked into the image; it must not download model files at
   request time. For an invitation-only deployment, provision the first owner
   through a controlled database/bootstrap procedure, then use workspace
   invitations for additional accounts.
3. Build and deploy the frontend with its server-only `BACKEND_URL` set to the reachable
   API origin and `NEXT_PUBLIC_TURNSTILE_SITE_KEY` set to the matching public
   Turnstile sitekey. Use Cloudflare's Managed widget mode and allow only the
   production frontend hostname. Deploy this frontend before enabling the new
   backend enforcement so the login form is already sending Turnstile tokens.
4. Run `alembic upgrade head` as a one-off release command, then deploy/start
   the API with `make start`. This auth migration intentionally invalidates
   legacy stateless JWTs, so users must sign in once after deployment.
5. Start the frontend with `npm start` when the build and runtime are separate.
6. Run `make email-worker` as a continuously supervised worker process. Signup,
   password-reset, and invitation messages remain queued until it is running.
7. Configure Stripe to call `/backend/billing/webhook` on the public frontend
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
If Cloudflare fronts the site, prevent direct origin access with Cloudflare
Tunnel, an origin firewall allowlist, or zone-specific Authenticated Origin
Pulls. A public origin IP would otherwise bypass the WAF and edge rules.

Production validation intentionally refuses placeholder secrets, localhost,
non-HTTPS browser/LLM URLs, non-TLS Redis, database URLs without `sslmode`,
insecure cookies, and missing billing/email/Turnstile configuration. Public
signup creates an inactive account and sends a single-use verification link;
after verification, the user must authenticate normally. New passwords use
Argon2id and existing bcrypt hashes upgrade after a successful login. Sessions
are recorded server-side and revoked on logout or password reset. TOTP MFA is
available from the Security page, including one-time recovery codes.

Collect the structured `hqlookup.security` logger in the production log
platform and alert on bursts of login/MFA failures, password resets, and rate
limit events. Do not log request bodies, bearer tokens, MFA secrets, or recovery
codes.

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
