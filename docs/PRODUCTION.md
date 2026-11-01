# Running RxGuard in production

One host with Docker Compose. Caddy terminates HTTPS and proxies to the API, which also serves the web app. PostgreSQL (with pgvector) holds everything, including the rate-limit counters. A one-shot bootstrap loads the data, and a backup service dumps the database nightly.

```
internet ──443──► caddy ──► api (uvicorn, models baked in) ──► postgres (pgvector)
                              ▲                                   ▲
                 bootstrap (once per deploy) ─────────────────────┤
                 backup (nightly pg_dump → backups volume) ───────┘
```

## 1. Requirements
- **Host:** Linux with Docker and Compose v2. 2 vCPU and 4 GB RAM for one API worker; each extra worker needs about 1 GB.
- **DNS:** `DOMAIN` points at the host, and ports 80 and 443 are open (Let's Encrypt needs both).
- **Gemini:** a Gemini API key on a **paid tier**. The free tier allows only a few calls per minute; past the quota or `GEMINI_DAILY_BUDGET`, answers quote the labels instead of failing.
- **Disk:** the image is about 3 GB (CPU PyTorch plus the two models); the database about 1 GB with all 500 labels.

## 2. Configure
```bash
cp .env.example .env
```
Set these values in `.env`:

| Variable | Value |
|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` (the API refuses to start with a weak or default one) |
| `DOMAIN` | e.g. `rxguard.example.org` |
| `GEMINI_API_KEY` | your key |
| `APP_ENV` | `production` (set by the compose file; hides `/docs` and refuses `CORS_ORIGINS=["*"]`) |
| `INCLUDE_DDINTER` | `true` for non-commercial use only (see section 7) |

Optional:
- `GEMINI_DAILY_BUDGET`
- the `RATE_LIMIT_*` per-IP limits
- `WEB_CONCURRENCY`
- `LIMIT` (labels fetched on first boot)
- `BACKUP_KEEP`
- `LOG_LEVEL`

## 3. Deploy
```bash
make prod-up        # docker compose -f deployment/docker-compose.prod.yml --env-file .env up -d --build
docker compose -f deployment/docker-compose.prod.yml logs -f bootstrap
```
**First boot:** the bootstrap migrates, seeds 500 drugs, fetches and embeds 500 FDA labels (about 20 minutes) and builds the interaction rules. The API starts only after it succeeds.

**Later deploys:** the bootstrap migrates and seeds, then skips the work already done.

**Database password:** PostgreSQL sets `POSTGRES_PASSWORD` only when its volume is first created. Changing it in `.env` later doesn't change the database's password; the bootstrap then fails with "password authentication failed". Change it inside the database with `ALTER USER … PASSWORD …`, or start fresh by deleting the `pgdata` volume, which **erases all data**.

**Checks once it's up:**
- `https://$DOMAIN/health`: liveness.
- `https://$DOMAIN/api/v1/ready`: rules, database and models loaded (`models: LOADED`).

## 4. Operate
| Task | How |
|---|---|
| Logs | `docker compose -f deployment/docker-compose.prod.yml logs -f api`. JSON lines; `request_id` matches the `X-Request-ID` response header |
| Refresh labels and rules monthly | cron: `0 3 1 * * cd /srv/rxguard && docker compose -f deployment/docker-compose.prod.yml run --rm bootstrap python -m src.rxguard.ops.bootstrap --refresh`, then `docker compose … restart api` |
| Upgrade | `git pull && make prod-up` (migrations run in the bootstrap) |
| Stop | `make prod-down` (volumes and data are kept) |
| Pin dependencies after changing `pyproject.toml` | `make lock`, then commit `requirements.lock` |

## 5. Backups and restore
- **Schedule:** the `backup` service writes `rxguard-YYYYMMDD-HHMMSS.dump` (pg_dump custom format) to the `backups` volume every 24 h and keeps the newest `BACKUP_KEEP`.
- **Off-site copy:**
  ```bash
  docker run --rm -v rxguard-prod_backups:/b -v "$PWD":/out alpine cp -r /b /out/backups
  ```
- **Restore:**
  ```bash
  docker compose -f deployment/docker-compose.prod.yml stop api
  docker compose -f deployment/docker-compose.prod.yml exec -T postgres \
    pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB" < rxguard-YYYYMMDD-HHMMSS.dump
  docker compose -f deployment/docker-compose.prod.yml start api
  ```

## 6. Security model
- **Network:** only Caddy is exposed (80/443, automatic HTTPS, HSTS). PostgreSQL and the API are internal.
- **Browser:** every response carries a strict Content-Security-Policy (scripts from the same origin only), `nosniff`, frame-deny, and referrer and permissions policies. CORS is same-origin unless `CORS_ORIGINS` lists origins.
- **Abuse and cost:**
  - **Per-IP limits** on chat, finding explanations, checks, search and registration (429 with `Retry-After`).
  - **Login lockout** after 5 failures in 15 minutes.
  - **Daily Gemini budget.**

  All of these are kept in PostgreSQL, so they survive restarts and hold across workers.
- **Auth:**
  - Argon2id password hashing and a strong-password policy.
  - Refresh tokens rotate, and reuse is detected.
  - Optional authenticator-app 2FA with one-time backup codes.
  - Accounts can't self-assign privileged roles.

## 7. Licensing, clinical and regulatory (not solved by code)
- **DDInter** supplies most interaction rules, under CC BY-NC-SA 4.0. Use it only for non-commercial research, and keep the attribution (shown in the app footer). For any commercial deployment, set `INCLUDE_DDINTER=false` (curated and FDA-label rules remain), or obtain permission.
- **Generated rules** (DDInter and FDA-label text) are marked *not clinically reviewed* in the app. Have a pharmacist or clinician review them before relying on them.
- **Regulatory status:** a public medication-interaction checker can count as clinical decision support (a regulated medical device in many jurisdictions). Get a regulatory assessment before offering it to patients. The app states it is a research prototype, not a medical device and not medical advice.
- **Gemini:** user questions are sent to Google's Gemini API. Disclose this in your privacy notice and use a paid tier with appropriate data terms.
