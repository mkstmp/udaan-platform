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
| **App URL (primary)** | https://udaan-platform-260701.web.app (Firebase Hosting → Cloud Run) |
| Cloud Run URL (direct) | https://udaan-api-md45haetfq-el.a.run.app |
| GCP project | `udaan-platform-260701` (region `asia-south1` — Mumbai) |
| Firestore | Native, `asia-south1` (seeded: 1 exam, 2 centres, 10 papers, admin allowlist) |
| Sample-papers bucket | `gs://udaan-platform-260701-udaan-papers` (public) |
| Image | `asia-south1-docker.pkg.dev/udaan-platform-260701/udaan/udaan-api` |
| Admins | `mkssmanish@gmail.com`, `mukesh.sonepur@gmail.com`, `rajnish.tarwan@gmail.com` |
| Budget alert | $25/mo (50/90/100% thresholds) |

Public pages work now (home, sample papers, student result lookup, leaderboard).

### Bihar geography (registration dropdowns)

`backend/app/bihar_geo.json` holds all **38 districts → 532 blocks** (with
generated stable codes), served read-only at **`GET /api/geo`**. Registration
shows statewide District/Block dropdowns from this; the **exam centre** (from
`centers/*`) is what actually seats a student — blocks without a centre show
"no centre yet" and can't submit. Add centres as venues are confirmed.

> Source: the supplied *Bihar Dis Block details* sheets (district → block).
> **Purnia** was missing from the source, so its 13 blocks were filled from the
> standard administrative list — **verify before launch**. District names were
> canonicalised (e.g. Gayaji→Gaya, Patliputra Patna→Patna) and codes generated
> (the sheet had none); ranking groups by *name*, so codes are cosmetic except
> the district code used in `student_id`.

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
- **Authorized JavaScript origins** including `https://udaan-platform-260701.web.app`
  (the primary URL) and any custom domain.
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
