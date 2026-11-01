# Deploy LabelSafe: step-by-step checklist

Tick each box as you go. Total time: about 25 minutes. Everything is free.

**Where things will live:**
- **Website** → Vercel (`label-safe.vercel.app`)
- **API (backend)** → Render (`labelsafe-api.onrender.com`)
- **Database** → Neon (already set up, with your data copied in)

Visitors only ever open the Vercel address. Vercel quietly forwards API calls to Render.

> Stuck on a step? See **deploy.md → section 9 (Troubleshooting)**.

---

## Before you start: have these ready

- [ ] **Neon direct connection string.** Find it in either place:
  - **Neon console** → your project → **Connect** → turn **Connection pooling OFF** → copy the string, or
  - **Vercel** → Storage → your Neon database → **.env.local** tab → copy the value of `DATABASE_URL_UNPOOLED`.

  It looks like `postgresql://neondb_owner:…@ep-….ap-southeast-1.aws.neon.tech/neondb?sslmode=require` and its host must **not** contain `-pooler`.
- [ ] **Gemini API key**, from <https://aistudio.google.com/apikey> (or your `.env` file, line `GEMINI_API_KEY=`)

---

## Part A: On your laptop (5 min)

**A1. Make sure the database re-embed finished.** In the project folder, run:

```bash
docker compose up -d --wait
DATABASE_URL='PASTE-NEON-DIRECT-URL-HERE' MODEL_MODE=fake .venv/bin/python -m src.labelsafe.ingestion.ingest_labels --limit 0
```

- [ ] The last line says `re-embedded 0 older passages with labelsafe-hashed-v1`, or another number. Either is fine: it just finished the rest.

**A2. Push the code to GitHub:**

```bash
git add -A
git commit -m "Deploy: Vercel frontend + Render API"
git push origin main
```

- [ ] On GitHub, the repo now shows **`render.yaml`** at the top level and **`frontend/vercel.json`** inside `frontend/`.

---

## Part B: Backend on Render (10 min)

- [ ] **B1.** Go to <https://render.com> → **Get Started** → **sign up with GitHub**.
- [ ] **B2.** In the Render dashboard, click **New +** (top right) → **Blueprint**.
- [ ] **B3.** Connect your GitHub account if asked. Give Render access to the **label-safe** repository, then select it.
- [ ] **B4.** Render reads `render.yaml` and shows one service, **labelsafe-api** (Free, Singapore). Give the Blueprint any name, e.g. `labelsafe`.
- [ ] **B5.** Fill in the two empty values:
  - `DATABASE_URL` → your **Neon direct connection string**
  - `GEMINI_API_KEY` → your **Gemini key**
- [ ] **B6.** Click **Apply** (or **Deploy Blueprint**).
- [ ] **B7.** Open the **labelsafe-api** service and wait until it says **Live** (3–5 minutes; you can watch the **Logs** tab).
- [ ] **B8.** Copy the service URL shown at the top (e.g. `https://labelsafe-api.onrender.com`) and open **`<that URL>/health`** in your browser. You should see `{"status":"HEALTHY", …}`.

**B9. Is the URL exactly `https://labelsafe-api.onrender.com`?**
- [ ] **Yes** → go to Part C.
- [ ] **No** (Render added a suffix such as `-x1y2`) → open `frontend/vercel.json` and replace `labelsafe-api.onrender.com` with your URL on all **3** `destination` lines. Then run:
  ```bash
  git add frontend/vercel.json && git commit -m "Point frontend at Render URL" && git push
  ```

---

## Part C: Website on Vercel (5 min)

Open <https://vercel.com> → your **label-safe** project.

- [ ] **C1.** Go to **Settings** → **Build and Deployment** (on some accounts it's under **General**) → **Root Directory** → click **Edit** → choose **`frontend`** → **Save**.
- [ ] **C2.** In the same settings, **Framework Preset** should now show **Vite**. If not, select **Vite** and save.
- [ ] **C3.** Go to **Settings** → **Environment Variables** and **delete** the old API variables: `JWT_SECRET_KEY`, `APP_ENV`, `MODEL_MODE`, `LLM_BACKEND`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_DAILY_BUDGET`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `RATE_LIMIT_…` and `LOG_LEVEL`. The website needs none of them. You can leave the Neon/Storage ones.
- [ ] **C4.** Go to **Deployments** → on the newest deployment click **⋯** → **Redeploy** → confirm.
- [ ] **C5.** Wait until the status says **Ready** (about 1 minute).

---

## Part D: Test it (2 min)

Open **<https://label-safe.vercel.app>**:

- [ ] The homepage loads and shows the medicine counts (e.g. "500 medicines to search"). That proves the website can reach the API.
- [ ] **<https://label-safe.vercel.app/health>** shows `{"status":"HEALTHY", …}`.
- [ ] Click **Start a check** → add **Warfarin** and **Ibuprofen** → **Check**. You should get a **Contraindicated** drug–drug risk, with an explanation that cites an FDA label.
- [ ] **Sign in → Create an account**, then sign in and save something on the **Profile** page.

All four work? **You're deployed.** 🎉

> If a check fails right after a quiet period, wait 30–60 seconds and try again. The free Render API was waking up. Part E stops that from happening.

---

## Part E: Keep the API awake (optional, 2 min)

Free Render services sleep after 15 minutes without visitors. This turns on a free GitHub job that pings the API every 14 minutes:

- [ ] **E1.** GitHub → your **label-safe** repo → **Settings** → **Secrets and variables** → **Actions** → **Variables** tab → **New repository variable**.
- [ ] **E2.** Name: `BACKEND_URL`. Value: your Render URL, e.g. `https://labelsafe-api.onrender.com` (no `/` at the end). Click **Add variable**.
- [ ] **E3.** Go to the **Actions** tab → **Keep backend awake** → **Run workflow** → **Run workflow**. A green ✓ means it works.

---

## Part F: Secure your database password (2 min)

Your Neon password was shared in a chat earlier, so give it a new one:

- [ ] **F1.** Neon console → your project → **Roles** (or **Branches → main → Roles**) → **neondb_owner** → **Reset password** → copy the **new connection string** (direct, not pooled).
- [ ] **F2.** Render → **labelsafe-api** → **Environment** → edit `DATABASE_URL` → paste the new string → **Save, rebuild, and deploy**.
- [ ] **F3.** When Render shows **Live** again, re-run the warfarin + ibuprofen check on the website.

---

## Later: shipping updates

| To… | Do |
|---|---|
| Update the app | `git push`. Render and Vercel both redeploy automatically. |
| Change an API setting or secret | Render → labelsafe-api → **Environment** → edit → **Save, rebuild, and deploy** |
| Anything else (migrations, more FDA labels, custom domain) | See **deploy.md**, sections 7–8 |

> **Never run `make neon-copy` again** once real people have accounts. It replaces the whole database, including their accounts.
