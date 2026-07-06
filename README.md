# Udaan — Deployment Kit

Everything to deploy V1 on Google Cloud (Cloud Run + Firestore). The exam is
**offline**; this backend handles registration, sample papers, admit cards,
marks upload, and results-with-slices. No SMS/OTP — adults use Google login,
students use a username (read-only, PII-free).

The FastAPI service also serves the single-page frontend (`frontend/index.html`)
same-origin, so the whole product runs as **one Cloud Run service**.

---

## ✅ Live deployment

| Thing | Value |
|---|---|
| **App URL (custom domain)** | https://hariharexam.com (Firebase Hosting → Cloud Run) |
| Firebase Hosting URL | https://udaan-platform-260701.web.app |
| Cloud Run URL (direct) | https://udaan-api-md45haetfq-el.a.run.app |
| GCP project | `udaan-platform-260701` (region `asia-south1` — Mumbai) |
| Firestore | Native, `asia-south1` (seeded: 1 exam, 2 centres, 10 papers, admin allowlist) |
| Sample-papers bucket | `gs://udaan-platform-260701-udaan-papers` (public) |
| Image | `asia-south1-docker.pkg.dev/udaan-platform-260701/udaan/udaan-api` |
| Admins | `mkssmanish@gmail.com`, `mukesh.sonepur@gmail.com`, `rajnish.tarwan@gmail.com` |
| Budget alert | $25/mo (50/90/100% thresholds) |

Public pages work now (home, sample papers, student result lookup, leaderboard).

### Bihar geography (registration dropdowns) — LGD-sourced

Full official hierarchy from the **Local Government Directory** (lgdirectory.gov.in,
1 Jul 2026 snapshot via the `ramSeraph/opendata` mirror):
**38 districts → 534 blocks (Panchayat Samiti) → 8,051 gram panchayats.**

- `backend/app/bihar_geo.json` (~26 KB) — districts + blocks → **`GET /api/geo`**.
- `backend/app/bihar_panchayats.json` (~452 KB) — district → block → gram
  panchayats → **`GET /api/geo/panchayats?district=&block=`** (lazy-loaded per
  block, so the client never pulls all 8k+ at once).

Registration flow is now **District → Block → Panchayat → Centre**. The student's
home gram panchayat drives the Panchayat-level rank; the **exam centre**
(`centers/*`) still gates the seat — blocks without a centre show "coming soon".
Block/district come from the LGD selection; panchayat from the chosen GP (falls
back to the centre's panchayat if a block has no GP list).

**Admins add centres in the console** (Admin → *Exam centres*): pick district →
block → panchayat from the same LGD dropdowns, set capacity + coordinator, save.
Registration opens for that district+block the moment an active centre exists.
Endpoints: `POST/GET /api/admin/centers`, `PATCH /api/admin/centers/{id}`
(activate/deactivate, capacity). The `seed_firestore.py` script is now optional.

> Codes: district codes are short/readable (pinned `DAR`/`MAD` to match seeded
> centres, since `student_id` = `UD-<district_code>-<seq>`); block and panchayat
> codes are the official LGD Localbody codes. Ranking groups by *name*.
> This LGD data supersedes the earlier hand-supplied district→block sheet
> (Purnia is now included natively).

### Test / demo mode (populated leaderboard + results before a real exam)

`scripts/seed_demo.py` creates a **self-contained DEMO exam** (`exam_id=udaan-demo`,
~400 students with marks + precomputed ranks + leaderboard, tagged `demo`/`is_demo`).
Because everything is keyed by `exam_id`, it never mixes with real data.

Admin → **Overview → Test/demo mode** toggles `settings/app.demo_visible`:
- **ON** → the DEMO exam appears in the public **Leaderboard / Results / Student
  login** exam pickers, so you can see fully populated screens.
- **OFF** (default) → hidden from the public (`/api/exams` filters `demo` exams;
  `/api/config` reports `demo_visible`).

Re-seed / wipe:
```bash
GOOGLE_CLOUD_PROJECT=udaan-platform-260701 python scripts/seed_demo.py         # seed
GOOGLE_CLOUD_PROJECT=udaan-platform-260701 python scripts/seed_demo.py --wipe  # remove
```

### Serving model + custom domain (Mumbai-safe path)

**Firebase Hosting** serves the SPA (`frontend/index.html`) as a static file and
rewrites `/api/**` to the Cloud Run service — same-origin, no CORS. Cloud Run's
built-in `run domain-mappings` isn't offered in `asia-south1`; Hosting works from
any region (verified end-to-end from Mumbai).

- **Ship a frontend change:** `firebase deploy --only hosting` (seconds).
- **Ship a backend change:** rebuild the image via `cloudbuild.yaml` (the image
  also bundles a copy of the SPA so the raw `run.app` URL still works standalone,
  but **`…web.app` is the canonical app URL**).
- **Custom domain:** Firebase Console → Hosting → Add custom domain → add the DNS
  records it shows (managed TLS issues automatically).

### ✅ Google sign-in is configured

`GOOGLE_CLIENT_ID` is set on Cloud Run, so "Sign in with Google" (register /
adult / admin) is live. The admin console is gated to the email(s) in Firestore
`admins/*`.

For sign-in to succeed in the browser, the OAuth client
(`623704019791-…apps.googleusercontent.com`) must have:
- **Authorized JavaScript origins** including `https://hariharexam.com`,
  `https://www.hariharexam.com`, and `https://udaan-platform-260701.web.app`.
  (The frontend uses relative `/api` URLs, so it needs no per-domain code change —
  only these origins must be authorized for Google sign-in.)
- An **OAuth consent screen** that's either **Published** (so any parent/teacher
  can sign in) or in Testing with the users added under *Test users*.

To rotate the client id later (no rebuild, ~30s redeploy):

```bash
gcloud run services update udaan-api --region asia-south1 \
  --update-env-vars GOOGLE_CLIENT_ID=NEW_CLIENT_ID.apps.googleusercontent.com
```

> **Health checks:** point uptime monitors at `/api/config` (returns 200).
> Google's edge returns a 404 for extensionless paths like `/healthz`, but every
> real route (`/`, `/api/*`) is unaffected.

---

> You run these commands. Claude can't reach your GCP project. Use your own
> machine or **Cloud Shell** (has `gcloud` + auth already).

```
udaan-deploy/
├── backend/            FastAPI app + Dockerfile
│   └── app/
│       ├── main.py             API routes
│       ├── student_payloads.py PII allowlist  ← the security-critical file
│       ├── db.py               Firestore access (transactions, idempotency)
│       ├── ranking.py          precompute rank slices at publish
│       ├── auth.py             Google OAuth verify + admin allowlist
│       └── usernames.py        unique, transliterated usernames
├── firestore/
│   ├── firestore.rules         deny direct client access to PII
│   └── firestore.indexes.json  composite indexes for slice queries
├── sample_papers/      the 10 bilingual PDFs (Class 9 & 10, Sets 1–5)
├── scripts/
│   └── seed_firestore.py       first exam, centres, admins, paper catalogue
├── cloudbuild.yaml     CI/CD → Cloud Run
└── README.md           (this file)
```

---

## 0. One-time setup

```bash
export PROJECT_ID="your-project-id"
export REGION="asia-south1"          # Mumbai — closest to users. Firestore region is PERMANENT.
export REPO="udaan"
export SERVICE="udaan-api"
export BUCKET="${PROJECT_ID}-udaan-papers"

gcloud config set project "$PROJECT_ID"

# Enable the APIs this kit uses.
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

## 1. Firestore (Native, permanent region)

```bash
gcloud firestore databases create --location="$REGION"
```

## 2. Service account for the backend (Workload Identity — no key files)

```bash
gcloud iam service-accounts create udaan-api --display-name="Udaan API"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:udaan-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:udaan-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

## 3. Google OAuth client (for admin + parent/teacher login)

In the Cloud Console → **APIs & Services → Credentials → Create OAuth client ID**
(Web application). Add your frontend URL to authorized origins. Copy the
**Client ID** — you'll pass it to the backend as `GOOGLE_CLIENT_ID`.
(The client *secret* is only needed if you do server-side OAuth code exchange;
for ID-token verification the Client ID is enough. Store any secret in Secret
Manager, never in code.)

## 4. Sample papers → Cloud Storage

```bash
gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" --uniform-bucket-level-access
gcloud storage cp sample_papers/*.pdf "gs://${BUCKET}/"

# Make the papers publicly readable (they're meant to be downloaded freely):
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member=allUsers --role=roles/storage.objectViewer
```

## 5. Artifact Registry + first deploy

```bash
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION"

# Build + deploy in one shot (Cloud Build reads cloudbuild.yaml):
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=${REGION},_REPO=${REPO},_SERVICE=${SERVICE},_GOOGLE_CLIENT_ID=YOUR_CLIENT_ID,_FRONTEND_ORIGIN=https://your-frontend-url
```

Grab the service URL:

```bash
gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
curl "$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')/healthz"
```

## 6. Deploy Firestore rules + indexes

```bash
# with the Firebase CLI (npm i -g firebase-tools; firebase login):
firebase deploy --only firestore:rules,firestore:indexes --project "$PROJECT_ID"
```
(If you don't use the Firebase CLI, paste `firestore/firestore.rules` in the
Console → Firestore → Rules, and create the indexes from
`firestore.indexes.json` when the first query prompts you.)

## 7. Seed the first exam + centres + admins + paper catalogue

```bash
pip install google-cloud-firestore
SAMPLE_PAPERS_BUCKET="$BUCKET" python scripts/seed_firestore.py
```
Edit `seed_firestore.py` first: set the real admin email(s) and real centres.

## 8. Operational must-dos (do these before launch day)

```bash
# Daily Firestore backups → a bucket
gcloud firestore export "gs://${BUCKET}-backups" --async   # schedule via Cloud Scheduler

# Billing budget alert (Console → Billing → Budgets) — set a monthly cap.

# Uptime check + alert (Console → Monitoring → Uptime checks) on /healthz.
```

Also verified/handled in code:
- **Idempotency / double-tap:** registration writes are transactional.
- **Last-seat race:** centre `used_capacity` updated inside a Firestore transaction.
- **PII boundary:** `student_payloads.py` builds student/admit payloads from an
  explicit allowlist and asserts no banned field leaks.

## 9. Custom domain (when you leave the run.app URL)

```bash
gcloud beta run domain-mappings create --service "$SERVICE" \
  --domain your-domain.org --region "$REGION"
```
Add the DNS records it prints; the managed TLS cert issues automatically
(allow time for DNS + cert). Do this a few days before you announce.

---

## What's deliberately NOT here (V2+)

SMS/OTP + DLT, online exam engine, AI answer-sheet scanning, video solutions,
daily homework, coaching CCTV/attendance, payments. Removing OTP is what let
this launch with **no external vendor and no lead-time dependency**.

## The 10 sample papers

Class 9 — Sets 1–5 (Number Systems & Polynomials).
Class 10 — Sets 1–5 (Real Numbers & Polynomials).
Bilingual (English + Hindi), 20 marks, 45 min, 3 sections (Easy/Intermediate/Hard).
Embedded Noto Sans Devanagari — render correctly in any PDF viewer.
```
