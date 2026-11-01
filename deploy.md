# Deploying LabelSafe (free: Vercel + Neon)

This guide takes LabelSafe from your laptop to a public `https://…vercel.app` address. It costs nothing on the free tiers and takes about 30 minutes.

```
                       ┌──────────────── Vercel project ────────────────┐
  visitor ──HTTPS──►   │  web service  (React site, served from the CDN) │
                       │  api service  (FastAPI, /api/*, /navigator)     │ ──► Neon Postgres (pgvector)
                       └─────────────────────────────────────────────────┘          ▲
                                                     Gemini API ◄── api              │
                                     your laptop: make neon-copy (one time) ──────────┘
```

**Lite mode:** on Vercel the app runs with `MODEL_MODE=fake`. The two torch ML models are too large for Vercel's serverless functions, so label search uses a built-in lightweight embedder and word-overlap reranker. Safety findings are exactly the same (they come from rules), and Gemini still writes the explanations.

---

## 0. What you need

| Thing | Notes |
|---|---|
| GitHub account | The repo: `github.com/hxrdikk21/label-safe` |
| Vercel account | Free **Hobby** plan. Sign up at vercel.com **with your GitHub account**. |
| Gemini API key | Free at <https://aistudio.google.com/apikey> |
| Your local LabelSafe database | Already set up if `make start` has worked on your laptop. Docker Desktop must be running. |

The Neon database is created from inside Vercel in step 3, so you don't need a separate Neon sign-up.

---

## 1. Push the code to GitHub

```bash
cd label-safe
git status                      # .env must NOT be listed (it holds your secrets; it's git-ignored)
git add -A
git commit -m "Prepare LabelSafe for Vercel"
git push origin main
```

Check that `data/generated/fda_label_rules.json` is in the commit. The app refuses to screen without its rulebook.

```bash
git ls-files data/generated     # should print data/generated/fda_label_rules.json
```

---

## 2. Create the Vercel project

1. Go to <https://vercel.com/new> and **Import** the `label-safe` repository.
2. Leave **Root Directory** as `./` and leave the build settings alone. `vercel.json` defines everything: a `web` service (the React site in `frontend/`) and an `api` service (FastAPI).
3. Open **Environment Variables** and add:

| Name | Value |
|---|---|
| `JWT_SECRET_KEY` | A long random string. Generate one with `openssl rand -hex 32`. **Required**: the API won't start without it. |
| `APP_ENV` | `production` |
| `MODEL_MODE` | `fake` (lite mode; **required**, since torch isn't installed on Vercel) |
| `LLM_BACKEND` | `gemini` |
| `GEMINI_API_KEY` | Your Gemini key |
| `GEMINI_MODEL` | `gemini-3.6-flash` |
| `DATABASE_POOL_SIZE` | `2` |
| `DATABASE_MAX_OVERFLOW` | `3` |

4. Click **Deploy**. The site loads, but checks fail until the database exists. That's expected; it's fixed in the next two steps.

---

## 3. Add a free Neon Postgres database

1. In your Vercel project, open the **Storage** tab, click **Create Database**, and choose **Neon** (Serverless Postgres).
2. Pick the **Free** plan and the region closest to your functions (the default `Washington, D.C. (iad1)` is fine). Create it.
3. When asked, **connect it to the `label-safe` project** for all environments. Vercel then adds `DATABASE_URL` and related variables to the project automatically. LabelSafe converts Neon's URL format by itself, so there's nothing to edit.

---

## 4. Copy your data to Neon (one command)

This copies your local database to Neon: the 500 drugs, 4,292 FDA label passages and the schema. It then rewrites the embeddings for lite mode, so search vectors match on Vercel.

1. Get Neon's **direct** connection string. In Vercel, go to **Storage → your Neon database → Quickstart / .env.local** and copy the value of **`DATABASE_URL_UNPOOLED`**. It looks like:
   `postgresql://neondb_owner:xxxx@ep-something-123456.us-east-1.aws.neon.tech/neondb?sslmode=require`
2. On your laptop, with Docker running:

```bash
docker compose up -d --wait     # your local Postgres
make neon-copy NEON_URL='postgresql://neondb_owner:xxxx@ep-something-123456.us-east-1.aws.neon.tech/neondb?sslmode=require'
```

It takes a minute or two and ends with `re-embedded 4292 older passages with labelsafe-hashed-v1`.

> **Warning:** `make neon-copy` **replaces** everything in the Neon database with your local copy, **including user accounts**. Run it once, before people sign up. To refresh labels later, see step 8.

---

## 5. Redeploy

The API only reads new environment variables on a fresh deployment. In Vercel, go to **Deployments**, open the **⋯** menu on the latest deployment, and choose **Redeploy**.

---

## 6. Check it works

Replace `<your-app>` with your project's address (shown on the Vercel dashboard):

| Check | Expected |
|---|---|
| `https://<your-app>.vercel.app` | The LabelSafe homepage, with the medicine counts filled in |
| `https://<your-app>.vercel.app/health` | `{"status":"HEALTHY", …}` |
| `https://<your-app>.vercel.app/api/v1/ready` | Database and rules reported as ready |
| On the site: **Start a check** with warfarin + ibuprofen | A **Contraindicated** drug–drug finding, with an explanation citing the FDA label |
| Create an account and sign in | Works, and your profile saves |

---

## 7. Your own domain (optional)

1. In Vercel, go to **Settings → Domains → Add** and follow the DNS instructions. HTTPS is automatic.
2. Replace the placeholder `labelsafe.example.com` with your domain in these three files, then commit and push:
   - `frontend/index.html` (canonical and social-preview tags)
   - `frontend/public/robots.txt`
   - `frontend/public/sitemap.xml`

---

## 8. Updating later

| You want to… | Do this |
|---|---|
| Ship a code change | `git push`. Vercel deploys every push to `main` automatically, and every pull request gets its own preview URL. |
| Change an environment variable | Vercel → **Settings → Environment Variables**, then **Redeploy** |
| Apply a database migration (a new file in `migrations/`) | `DATABASE_URL='<DATABASE_URL_UNPOOLED>' .venv/bin/alembic upgrade head` |
| Fetch more or newer FDA labels into Neon | `DATABASE_URL='<DATABASE_URL_UNPOOLED>' MODEL_MODE=fake .venv/bin/python -m src.labelsafe.ingestion.ingest_labels --limit 500`. Then run `make rules` locally, and commit and push `data/generated/fda_label_rules.json`. This keeps user accounts. |

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Checks fail with a server error right after setup | You skipped **Redeploy** (step 5), or Neon isn't connected to the project (step 3). |
| Runtime logs say "No safety rules loaded" | `data/generated/fda_label_rules.json` isn't committed. See step 1. |
| Errors mentioning "prepared statement" | Neon's pooled URL is the culprit. In **Settings → Environment Variables**, set `DATABASE_URL` to the value of `DATABASE_URL_UNPOOLED` and redeploy. |
| The first request after a quiet period is slow (1–3 s) | Normal on free tiers: Neon wakes its database and Vercel starts a function. |
| Explanations quote the label instead of a written answer | Gemini's free tier is rate-limited. The app falls back to quoting the label text rather than failing. A paid Gemini key removes this. |
| `make neon-copy` says `NEON_URL` is missing | Pass it on the same line, in single quotes, exactly as in step 4. |
| Build fails mentioning `services` | Vercel Services is in Beta. Check the build log; the Vercel docs at vercel.com/docs/services have the current syntax. |

Logs live in Vercel → your project → **Logs** (filter by the `api` service). Each line carries a `request_id`, which matches the `X-Request-ID` response header.

---

## 10. Free-tier limits and rules

- **Vercel Hobby** is for personal, **non-commercial** projects. That fits LabelSafe: its DDInter-derived data is also non-commercial only.
- **Neon Free** gives 0.5 GB of storage (LabelSafe uses about 0.15 GB) and pauses the database when idle. It wakes automatically.
- **Gemini free tier** allows a limited number of requests per minute and per day.
- **Medical disclaimer:** LabelSafe is a research prototype, not a medical device. The site says so on every page and in the Terms. Keep it that way if you share the link.
