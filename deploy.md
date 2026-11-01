# Deploying LabelSafe (free: Vercel + Render + Neon)

> Want a click-by-click checklist instead? Follow [DEPLOY_STEPS.md](DEPLOY_STEPS.md). This page explains the setup and covers troubleshooting.

LabelSafe runs in three free pieces:

```
  visitor ──HTTPS──► Vercel  (website: React, from frontend/)
                       │  /api/*, /health, /navigator are forwarded ──►  Render  (API: FastAPI, render.yaml)
                       │                                                    │
                       └── the browser only ever talks to Vercel            ├──► Neon   (Postgres + pgvector)
                                                                            └──► Gemini (written explanations)
```

Because Vercel forwards the API calls, the browser sees one address, so no CORS setup is needed.

**Lite mode:** the API runs with `MODEL_MODE=fake`. The torch ML models don't fit in Render's free 512 MB instance, so label search uses a built-in lightweight embedder and word-overlap reranker. Safety findings are identical (they come from rules), and Gemini still writes the explanations.

---

## 0. What you need

| Thing | Notes |
|---|---|
| GitHub repo | `github.com/hxrdikk21/label-safe`, with your latest code pushed (step 2) |
| Vercel account | Free Hobby plan, signed in with GitHub. You already have the project `label-safe`. |
| Render account | Free. Sign up at <https://render.com> **with your GitHub account**. |
| Neon database | Free. You already created it and copied your data in (step 1 checks it). |
| Gemini API key | <https://aistudio.google.com/apikey> |

---

## 1. Database (Neon): check it's ready

You've already run `make neon-copy`. Make sure the lite-mode re-embed finished. Running this again is safe: it only processes passages that still need it, and prints `re-embedded 0 …` when everything is done:

```bash
docker compose up -d --wait
DATABASE_URL='<your Neon connection string>' MODEL_MODE=fake .venv/bin/python -m src.labelsafe.ingestion.ingest_labels --limit 0
```

Use Neon's **direct** connection string (host without `-pooler`). You'll find it in the Neon console under **Connect**, or in Vercel → Storage → your database → `DATABASE_URL_UNPOOLED`. It looks like
`postgresql://neondb_owner:…@ep-….ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.

Starting from scratch instead? Create a free project at <https://neon.tech> (region **Singapore**), then run `make neon-copy NEON_URL='<connection string>'` once.

---

## 2. Push the code

```bash
git add -A
git commit -m "Deploy: Vercel frontend + Render API"
git push origin main
```

Check that `data/generated/fda_label_rules.json` is committed (`git ls-files data/generated`). The API refuses to screen without its rulebook.

---

## 3. Backend on Render (about 5 minutes)

1. In Render, click **New → Blueprint** and connect the `label-safe` repository. Render finds `render.yaml` and shows one service, **labelsafe-api** (free, Singapore).
2. It asks for two values:
   - `DATABASE_URL`: your Neon **direct** connection string from step 1
   - `GEMINI_API_KEY`: your Gemini key

   Everything else is preset in `render.yaml`. Render generates `JWT_SECRET_KEY` itself.
3. Click **Apply**. The first build takes 3–5 minutes (it installs dependencies with `uv`).
4. When it shows **Live**, open `https://labelsafe-api.onrender.com/health`. You should see `{"status":"HEALTHY", …}`. Then try `/api/v1/ready`, which should report the database and rules as ready.

> **Is your service's URL different?** Render adds a suffix if `labelsafe-api` is taken (e.g. `labelsafe-api-x1y2.onrender.com`). If so, put your URL in the **three** `destination` lines of `frontend/vercel.json`, then commit and push.

---

## 4. Frontend on Vercel

Your existing Vercel project currently tries to build the API too. Point it at the website only:

1. In Vercel, open the `label-safe` project → **Settings → Build and Deployment** (or **General**) → **Root Directory**. Set it to `frontend` and save. The Framework Preset becomes **Vite** automatically.
2. Under **Settings → Environment Variables**, delete the old API variables (`JWT_SECRET_KEY`, `GEMINI_API_KEY`, `MODEL_MODE` and so on). The website needs none, and the API's secrets now live on Render. You can leave the Neon integration connected; it's harmless.
3. Go to **Deployments → ⋯ → Redeploy**, or just push a commit.

(Creating a fresh project instead: <https://vercel.com/new> → import the repo → set **Root Directory** to `frontend` → Deploy.)

---

## 5. Check it works

Open `https://label-safe.vercel.app` (or your project's address):

| Check | Expected |
|---|---|
| Homepage | Loads, with the medicine counts filled in. Those come from the API, so this proves the forwarding works. |
| `https://label-safe.vercel.app/health` | `{"status":"HEALTHY", …}` (served by Render through Vercel) |
| **Start a check** → warfarin + ibuprofen | A **Contraindicated** drug–drug finding, with an explanation citing the FDA label |
| Create an account, sign in, save your profile | Works |

---

## 6. Keep the API awake (optional, recommended)

A free Render service **sleeps after 15 minutes without traffic**. The next visitor then waits 30–60 s, and that first request may fail once while it wakes. The repo includes a GitHub Actions job that pings the API every 14 minutes. One always-on service fits inside Render's 750 free hours a month.

Turn it on: GitHub → your repo → **Settings → Secrets and variables → Actions → Variables → New repository variable**. Name it `BACKEND_URL` and set it to `https://labelsafe-api.onrender.com` (your Render URL, no trailing slash). To test it, go to **Actions → Keep backend awake → Run workflow**.

---

## 7. Your own domain (optional)

1. Add the domain to the **Vercel** project (**Settings → Domains**). HTTPS is automatic. Render needs no domain, because visitors never call it directly.
2. Replace the placeholder `labelsafe.example.com` with your domain in `frontend/index.html`, `frontend/public/robots.txt` and `frontend/public/sitemap.xml`, then push.

---

## 8. Updating later

| You want to… | Do this |
|---|---|
| Ship a code change | `git push`. Render redeploys the API and Vercel redeploys the website automatically. |
| Change an API setting or secret | Render → `labelsafe-api` → **Environment** → edit → **Save, rebuild, and deploy** |
| Apply a database migration | `DATABASE_URL='<Neon direct URL>' .venv/bin/alembic upgrade head` |
| Fetch more or newer FDA labels | `DATABASE_URL='<Neon direct URL>' MODEL_MODE=fake .venv/bin/python -m src.labelsafe.ingestion.ingest_labels --limit 500`. Then run `make rules`, and commit and push `data/generated/fda_label_rules.json`. This keeps user accounts. |

> **Warning:** don't run `make neon-copy` again once people have signed up. It **replaces** the whole Neon database with your local one, including accounts.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Site loads but every check says "Request failed" | The API isn't reachable. Open `https://labelsafe-api.onrender.com/health` directly. If that fails, check the Render **Logs**. If it works, check the URL in `frontend/vercel.json` and the Root Directory (step 4). |
| The first check after a quiet period fails or takes about a minute | Render was asleep. Retry, or turn on step 6. |
| Render build fails | Open the deploy's log in Render. A missing `uv.lock` or Python version error means the latest code isn't pushed (step 2). |
| Render logs say "Set JWT_SECRET_KEY…" | The variable is missing. Render → Environment → add `JWT_SECRET_KEY` (any random 64-character string, e.g. from `openssl rand -hex 32`). |
| Render logs say "No safety rules loaded" | `data/generated/fda_label_rules.json` isn't committed (step 2). |
| Database connection errors in Render logs | Check `DATABASE_URL` on Render is Neon's direct URL, with `?sslmode=require`. |
| Explanations quote the label instead of a written answer | Gemini's free tier is rate-limited; the app falls back to quoting the label. A paid key removes this. |

**Logs:** Render → `labelsafe-api` → **Logs** (API). Vercel → project → **Logs** (website and forwarding).

---

## 10. Free-tier limits

- **Render Free:** 512 MB RAM, sleeps after 15 idle minutes, 750 instance-hours a month.
- **Vercel Hobby:** personal, **non-commercial** use. That matches LabelSafe's non-commercial DDInter data licence.
- **Neon Free:** 0.5 GB storage (LabelSafe uses about 0.15 GB). It pauses when idle and wakes automatically.
- **Gemini free tier:** limited requests per minute and per day.

**Security:** if your Neon password was ever shared (for example, pasted into a chat), reset it in the Neon console (**Roles → neondb_owner → Reset password**), then update `DATABASE_URL` on Render.
