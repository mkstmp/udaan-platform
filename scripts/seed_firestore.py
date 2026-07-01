"""
Seed Firestore with the first exam, a few centres, the admin allowlist,
and the sample-paper catalogue (pointing at the PDFs in Cloud Storage).

Run locally with ADC:  python scripts/seed_firestore.py
Requires: pip install google-cloud-firestore
Set BUCKET to your sample-papers bucket before running.
"""
import os
from google.cloud import firestore

db = firestore.Client()
BUCKET = os.environ.get("SAMPLE_PAPERS_BUCKET", "udaan-sample-papers")
# Comma-separated admin emails, e.g. ADMIN_EMAILS="a@x.com,b@y.com".
ADMIN_EMAILS = [e.strip().lower() for e in
                os.environ.get("ADMIN_EMAILS", "you@example.com").split(",") if e.strip()]

EXAM_ID = "udaan-2026-08-math"

def seed():
    # --- exam ---
    db.collection("exams").document(EXAM_ID).set({
        "exam_id": EXAM_ID,
        "name": "Udaan Talent Test — August 2026",
        "subject": "Mathematics",
        "exam_date": "2026-08-15",
        "exam_start_time": "10:00 AM",
        "exam_end_time": "12:00 PM",
        "reporting_time": "9:30 AM",
        "registration_start": "2026-06-15",
        "registration_end": "2026-08-05",
        "eligible_classes": [7, 8, 9, 10],
        "status": "open",
        "results_published": False,
    })

    # --- centres (add real ones) ---
    centers = [
        {"center_id": "DAR-BEN-RAS", "name": "Rasalpur Panchayat Centre",
         "district_name": "Darbhanga", "district_code": "DAR",
         "block_name": "Benipur", "block_code": "BEN",
         "panchayat_name": "Rasalpur", "panchayat_code": "RAS",
         "capacity": 120, "used_capacity": 0, "active": True, "exam_id": EXAM_ID},
        {"center_id": "MAD-RAJ-BHI", "name": "Bhitthi Panchayat Centre",
         "district_name": "Madhubani", "district_code": "MAD",
         "block_name": "Rajnagar", "block_code": "RAJ",
         "panchayat_name": "Bhitthi", "panchayat_code": "BHI",
         "capacity": 120, "used_capacity": 0, "active": True, "exam_id": EXAM_ID},
    ]
    for c in centers:
        db.collection("centers").document(c["center_id"]).set(c)

    # --- admin allowlist (set via ADMIN_EMAILS env var) ---
    for email in ADMIN_EMAILS:
        db.collection("admins").document(email).set({"role": "super_admin"})

    # --- sample papers catalogue ---
    papers = []
    for cls in (9, 10):
        for s in range(1, 6):
            fname = f"Class_{cls}_Maths_Bilingual_Set_{s}.pdf"
            papers.append({
                "paper_id": f"c{cls}-set{s}",
                "exam_id": EXAM_ID,
                "class": cls,
                "subject": "Mathematics",
                "title": f"Class {cls} Mathematics — Sample Set {s} (Bilingual)",
                "pdf_url": f"https://storage.googleapis.com/{BUCKET}/{fname}",
                "answer_key_url": None,
                "active": True,
            })
    for p in papers:
        db.collection("sample_papers").document(p["paper_id"]).set(p)

    print(f"Seeded exam {EXAM_ID}, {len(centers)} centres, {len(papers)} sample papers.")

if __name__ == "__main__":
    seed()
