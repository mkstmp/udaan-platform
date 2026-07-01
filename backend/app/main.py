"""
Udaan backend — FastAPI on Cloud Run, Firestore (Admin SDK).

Security spine:
- ALL Firestore writes happen here via the Admin SDK (service account),
  never from the client. Firestore rules deny direct client access.
- Student read-view + admit card are built from an EXPLICIT FIELD ALLOWLIST
  (see student_payloads.py). A whitelist fails safe; adding a PII field to
  the student record can never accidentally leak it.
- Adult endpoints only return students where created_by_uid == caller's uid.
- Admin endpoints require the caller's Google email to be in admins/*.
"""

import csv
import io
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from . import db, auth, ranking
from .student_payloads import student_result_view, admit_card_view
from .usernames import make_username

app = FastAPI(title="Udaan API")

# Directory holding the built single-page frontend (served same-origin below).
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# CORS: lock to your real frontend origin(s) in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ----------------------------------------------------------------------------
# PUBLIC REFERENCE DATA (no auth; safe fields only)
# ----------------------------------------------------------------------------

@app.get("/api/config")
def public_config():
    """Client bootstrap: the OAuth client id the frontend needs to init Google sign-in."""
    return {"google_client_id": os.environ.get("GOOGLE_CLIENT_ID", "")}


@app.get("/api/exams")
def list_exams():
    """Public list of exams (open/closed/completed) for the home page + pickers."""
    return db.list_open_exams()


@app.get("/api/sample-papers")
def list_sample_papers(exam_id: Optional[str] = None):
    """Public, no login (spec §5.2 / acceptance #8)."""
    return db.list_sample_papers(exam_id)


@app.get("/api/centers")
def list_centers(exam_id: Optional[str] = None):
    """Public, PII-free centre list — powers the registration location picker."""
    return db.list_centers_public(exam_id)


# ----------------------------------------------------------------------------
# PUBLIC / STUDENT (username-only, read-only, PII-free)
# ----------------------------------------------------------------------------

@app.get("/api/student/{username}/result")
def get_student_result(username: str, exam_id: str):
    """Username-only lookup. Returns ONLY the PII-free allowlisted result view."""
    student = db.get_student_by_username(username)
    if not student:
        raise HTTPException(404, "No student found with that username.")
    reg = db.get_registration(exam_id=exam_id, student_id=student["student_id"])
    if not reg or reg.get("status") != "published":
        raise HTTPException(404, "Result not available yet for this exam.")
    return student_result_view(student, reg)  # <-- allowlist enforced here


@app.get("/api/student/{username}/admit-card")
def get_student_admit_card(username: str, exam_id: str):
    """Username-only. Returns ONLY the PII-free admit-card fields."""
    student = db.get_student_by_username(username)
    if not student:
        raise HTTPException(404, "No student found with that username.")
    reg = db.get_registration(exam_id=exam_id, student_id=student["student_id"])
    if not reg:
        raise HTTPException(404, "Not registered for this exam.")
    exam = db.get_exam(exam_id)
    center = db.get_center(reg["center_id"])
    return admit_card_view(student, reg, exam, center)  # <-- allowlist enforced


@app.get("/api/leaderboard")
def get_leaderboard(exam_id: str, cls: int, scope: str, scope_value: Optional[str] = None):
    """Public leaderboard (already-public info). scope: panchayat|block|district|state."""
    return db.leaderboard(exam_id=exam_id, cls=cls, scope=scope, scope_value=scope_value)


# ----------------------------------------------------------------------------
# ADULT (parent/teacher) — Google OAuth required; own students only
# ----------------------------------------------------------------------------

class StudentIn(BaseModel):
    exam_id: str
    name: str
    guardian_name: str
    dob: Optional[str] = None          # PRIVATE
    gender: Optional[str] = None
    school_name: str                    # PRIVATE
    medium: str
    cls: int
    district_name: str; district_code: str
    block_name: str;    block_code: str
    panchayat_name: str; panchayat_code: str
    village_name: Optional[str] = None; village_code: Optional[str] = None  # PRIVATE
    center_id: str


@app.post("/api/adult/students")
def enroll_student(payload: StudentIn, adult=Depends(auth.require_adult)):
    """Create a student under the authenticated adult and register for an exam."""
    exam = db.get_exam(payload.exam_id)
    if not exam or exam["status"] != "open":
        raise HTTPException(400, "Registration is not open for this exam.")

    student_id = db.next_student_id(payload.district_code)
    username = make_username(payload.name, exists=db.username_exists)

    student = {
        "student_id": student_id,
        "username": username,
        "username_lc": username.lower(),
        "name": payload.name,
        "guardian_name": payload.guardian_name,
        "dob": payload.dob,                 # stored, never in student view/card
        "gender": payload.gender,
        "school_name": payload.school_name, # stored, never in student view/card
        "medium": payload.medium,
        "class": payload.cls,
        "district_name": payload.district_name, "district_code": payload.district_code,
        "block_name": payload.block_name,       "block_code": payload.block_code,
        "panchayat_name": payload.panchayat_name, "panchayat_code": payload.panchayat_code,
        "village_name": payload.village_name,   "village_code": payload.village_code,
        "created_by_uid": adult["uid"],
        "created_by_email": adult["email"],
    }
    reg = db.create_student_and_registration(student, payload.exam_id, payload.center_id)
    # Return the username to show ONCE on the confirmation screen.
    return {"student_id": student_id, "username": username, "registration_id": reg["registration_id"]}


@app.get("/api/adult/students")
def list_my_students(adult=Depends(auth.require_adult)):
    """Full detail (incl. PII) — but ONLY for students this adult created."""
    return db.students_by_creator(adult["uid"])


# ----------------------------------------------------------------------------
# ADMIN — Google OAuth + email allowlist
# ----------------------------------------------------------------------------

class MarksRow(BaseModel):
    student_id: str
    marks_obtained: float


class MarksUpload(BaseModel):
    exam_id: str
    rows: list[MarksRow]


@app.post("/api/admin/marks")
def upload_marks(payload: MarksUpload, admin=Depends(auth.require_admin)):
    """Validate + save marks. Unmatched student_ids are flagged, not dropped."""
    matched, unmatched = db.apply_marks(payload.exam_id, [r.model_dump() for r in payload.rows])
    return {"matched": matched, "unmatched": unmatched, "published": False}


@app.post("/api/admin/publish")
def publish_results(exam_id: str, admin=Depends(auth.require_admin)):
    """Precompute all four rank slices per registration, write leaderboard, mark published."""
    count = ranking.compute_and_publish(exam_id)
    return {"published_registrations": count, "exam_id": exam_id}


@app.get("/api/admin/registrations")
def admin_registrations(exam_id: str, cls: Optional[int] = None,
                        district: Optional[str] = None, fmt: Optional[str] = None,
                        admin=Depends(auth.require_admin)):
    rows = db.query_registrations(exam_id=exam_id, cls=cls, district=district)
    if fmt == "csv":
        cols = ["student_id", "student_name", "class", "roll_number", "center_name",
                "panchayat_name", "block_name", "district_name", "status",
                "marks_obtained", "total_marks"]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="registrations_{exam_id}.csv"'})
    return rows


@app.get("/api/admin/results")
def admin_results(exam_id: str, cls: Optional[int] = None,
                  district: Optional[str] = None, admin=Depends(auth.require_admin)):
    """Slice-and-dice: distribution + top-N for the selected filter."""
    return db.results_slice(exam_id=exam_id, cls=cls, district=district)


# ----------------------------------------------------------------------------
# STATIC FRONTEND (same-origin SPA — no CORS, one Cloud Run service)
# ----------------------------------------------------------------------------
# Mounted last so /api/* and /healthz always win. Any non-API path serves the
# SPA shell (index.html); the client-side router handles the route.

if _FRONTEND_DIR.is_dir():
    @app.get("/")
    def _spa_root():
        return FileResponse(_FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
