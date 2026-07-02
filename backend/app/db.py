"""
Firestore access layer (Admin SDK). Runs as the Cloud Run service account,
so it bypasses security rules — this is the ONLY writer.
"""
import os
from google.cloud import firestore

_db = firestore.Client()  # uses Workload Identity / ADC on Cloud Run


# ---- reads -----------------------------------------------------------------

def get_exam(exam_id):
    d = _db.collection("exams").document(exam_id).get()
    return d.to_dict() if d.exists else None

def get_center(center_id):
    d = _db.collection("centers").document(center_id).get()
    return d.to_dict() if d.exists else None

def get_student_by_username(username):
    q = (_db.collection("students")
            .where("username_lc", "==", (username or "").lower()).limit(1).stream())
    for d in q:
        return d.to_dict()
    return None

def get_student(student_id):
    """Full student record by id (admin-only view — includes PII)."""
    d = _db.collection("students").document(student_id).get()
    return d.to_dict() if d.exists else None


def registrations_for_student(student_id):
    """All registrations for a student across exams (admin detail view)."""
    q = _db.collection("registrations").where("student_id", "==", student_id).stream()
    return [d.to_dict() for d in q]


def username_exists(username_lc):
    q = _db.collection("students").where("username_lc", "==", username_lc).limit(1).stream()
    return any(True for _ in q)

def get_registration(exam_id, student_id):
    q = (_db.collection("registrations")
            .where("exam_id", "==", exam_id)
            .where("student_id", "==", student_id).limit(1).stream())
    for d in q:
        return d.to_dict()
    return None

def students_by_creator(uid):
    q = (_db.collection("students").where("created_by_uid", "==", uid)
            .order_by("created_at", direction=firestore.Query.DESCENDING).stream())
    return [d.to_dict() for d in q]

def is_admin(email):
    return _db.collection("admins").document(email).get().exists


def get_settings():
    """App-wide settings (e.g. demo_visible). Defaults when the doc is absent."""
    d = _db.collection("settings").document("app").get()
    s = d.to_dict() if d.exists else {}
    return {"demo_visible": bool(s.get("demo_visible", False))}


def set_settings(patch):
    _db.collection("settings").document("app").set(patch, merge=True)
    return get_settings()


def list_open_exams():
    """Public: exams the frontend may show (open/closed/completed)."""
    out = []
    for d in _db.collection("exams").stream():
        e = d.to_dict()
        if e.get("status") in ("open", "closed", "completed"):
            out.append(e)
    return out


def list_sample_papers(exam_id=None):
    """Public: active sample papers, optionally scoped to an exam."""
    q = _db.collection("sample_papers").where("active", "==", True)
    if exam_id:
        q = q.where("exam_id", "==", exam_id)
    papers = [d.to_dict() for d in q.stream()]
    papers.sort(key=lambda p: (p.get("class", 0), p.get("title", "")))
    return papers


# Public-safe center fields (NO coordinator phone) for the registration picker.
_CENTER_PUBLIC = ("center_id", "name", "district_name", "district_code",
                  "block_name", "block_code", "panchayat_name", "panchayat_code",
                  "capacity", "used_capacity")


def list_centers_public(exam_id=None):
    """Public: active centres with an allowlisted (PII-free) field set."""
    q = _db.collection("centers").where("active", "==", True)
    if exam_id:
        q = q.where("exam_id", "==", exam_id)
    out = []
    for d in q.stream():
        c = d.to_dict()
        row = {k: c.get(k) for k in _CENTER_PUBLIC}
        row["seats_left"] = max(0, (c.get("capacity", 0) - c.get("used_capacity", 0)))
        out.append(row)
    out.sort(key=lambda c: (c.get("district_name", ""), c.get("block_name", ""),
                            c.get("panchayat_name", "")))
    return out


# ---- adults ----------------------------------------------------------------

def upsert_adult(identity):
    ref = _db.collection("adults").document(identity["uid"])
    if not ref.get().exists:
        ref.set({**identity, "created_at": firestore.SERVER_TIMESTAMP})


# ---- ids -------------------------------------------------------------------

def next_student_id(district_code):
    """Atomic per-district counter -> UD-<CODE>-<seq zero-padded>."""
    counter = _db.collection("counters").document(f"student_seq_{district_code}")

    @firestore.transactional
    def _txn(txn):
        snap = counter.get(transaction=txn)
        n = (snap.to_dict() or {}).get("n", 0) + 1 if snap.exists else 1
        txn.set(counter, {"n": n})
        return n

    n = _txn(_db.transaction())
    return f"UD-{district_code}-{n:04d}"


# ---- writes ----------------------------------------------------------------

def create_student_and_registration(student, exam_id, center_id):
    """Transaction: decrement centre capacity + write student + registration."""
    center_ref = _db.collection("centers").document(center_id)
    student_ref = _db.collection("students").document(student["student_id"])
    reg_ref = _db.collection("registrations").document()

    @firestore.transactional
    def _txn(txn):
        c = center_ref.get(transaction=txn).to_dict()
        if c is None:
            raise ValueError("Center not found.")
        if c.get("used_capacity", 0) >= c.get("capacity", 0):
            raise ValueError("Center is full.")

        txn.set(student_ref, {**student,
                              "created_at": firestore.SERVER_TIMESTAMP,
                              "updated_at": firestore.SERVER_TIMESTAMP})
        reg = {
            "registration_id": reg_ref.id,
            "exam_id": exam_id,
            "student_id": student["student_id"],
            "student_name": student["name"],
            "class": student["class"],
            "center_id": center_id,
            "center_name": c.get("name"),
            "roll_number": student["student_id"],  # unique, non-PII; prints on admit card
            "panchayat_name": student["panchayat_name"],
            "block_name": student["block_name"],
            "district_name": student["district_name"],
            "status": "submitted",
            "marks_obtained": None,
            "total_marks": 100,
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        txn.set(reg_ref, reg)
        txn.update(center_ref, {"used_capacity": c.get("used_capacity", 0) + 1})
        return reg

    return _txn(_db.transaction())


def create_center(data):
    """Admin: create an exam centre (auto id == center_id; used_capacity starts 0)."""
    ref = _db.collection("centers").document()
    doc = {**data, "center_id": ref.id, "used_capacity": 0,
           "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP}
    ref.set(doc)
    return {"center_id": ref.id}


def list_centers_admin(exam_id):
    """Admin: all centres for an exam (full fields incl. coordinator + usage)."""
    q = _db.collection("centers").where("exam_id", "==", exam_id)
    rows = [d.to_dict() for d in q.stream()]
    rows.sort(key=lambda c: (c.get("district_name", ""), c.get("block_name", ""), c.get("name", "")))
    return rows


def update_center(center_id, patch):
    """Admin: update allowed centre fields (capacity, active, coordinator, name, address)."""
    ref = _db.collection("centers").document(center_id)
    if not ref.get().exists:
        return None
    ref.update({**patch, "updated_at": firestore.SERVER_TIMESTAMP})
    return {"center_id": center_id, "updated": True}


def apply_marks(exam_id, rows):
    matched, unmatched = 0, []
    batch = _db.batch()
    for row in rows:
        reg = get_registration(exam_id, row["student_id"])
        if not reg:
            unmatched.append(row["student_id"]); continue
        ref = _db.collection("registrations").document(reg["registration_id"])
        batch.update(ref, {"marks_obtained": row["marks_obtained"],
                           "status": "marks_uploaded",
                           "updated_at": firestore.SERVER_TIMESTAMP})
        matched += 1
    batch.commit()
    return matched, unmatched


def registrations_with_marks(exam_id):
    q = (_db.collection("registrations").where("exam_id", "==", exam_id)
            .where("marks_obtained", ">", -1).stream())  # not null
    return [d.to_dict() for d in q if d.to_dict().get("marks_obtained") is not None]


def batch_update_registrations(updates):
    batch = _db.batch()
    for rid, patch in updates:
        # rid is registration_id; doc id == registration_id
        ref = _db.collection("registrations").document(rid)
        batch.update(ref, {**patch, "updated_at": firestore.SERVER_TIMESTAMP})
    batch.commit()


def replace_leaderboard(exam_id, rows):
    # wipe old entries for this exam, write fresh
    old = _db.collection("leaderboard").where("exam_id", "==", exam_id).stream()
    batch = _db.batch()
    for d in old:
        batch.delete(d.reference)
    for row in rows:
        batch.set(_db.collection("leaderboard").document(), row)
    batch.commit()


def mark_exam_published(exam_id):
    _db.collection("exams").document(exam_id).update({"results_published": True,
                                                     "status": "completed"})


# ---- queries for admin & public -------------------------------------------

def query_registrations(exam_id, cls=None, district=None):
    q = _db.collection("registrations").where("exam_id", "==", exam_id)
    if cls is not None:    q = q.where("class", "==", cls)
    if district:           q = q.where("district_name", "==", district)
    return [d.to_dict() for d in q.limit(500).stream()]


def leaderboard(exam_id, cls, scope, scope_value=None):
    q = (_db.collection("leaderboard").where("exam_id", "==", exam_id)
            .where("class", "==", cls))
    if scope != "state" and scope_value:
        q = q.where(f"{scope}_name", "==", scope_value)
    rows = [d.to_dict() for d in q.stream()]
    rows.sort(key=lambda r: r["marks_obtained"], reverse=True)
    return rows[:50]


def results_slice(exam_id, cls=None, district=None):
    regs = query_registrations(exam_id, cls, district)
    scored = [r for r in regs if r.get("marks_obtained") is not None]
    if not scored:
        return {"count": 0, "average": None, "top": [], "distribution": {}}
    avg = round(sum(r["marks_obtained"] for r in scored) / len(scored), 1)
    top = sorted(scored, key=lambda r: r["marks_obtained"], reverse=True)[:10]
    buckets = {"<40": 0, "40-59": 0, "60-74": 0, "75-89": 0, "90+": 0}
    for r in scored:
        m = r["marks_obtained"]
        k = "<40" if m < 40 else "40-59" if m < 60 else "60-74" if m < 75 else "75-89" if m < 90 else "90+"
        buckets[k] += 1
    return {"count": len(scored), "average": avg,
            "top": [{"name": r["student_name"], "class": r["class"],
                     "panchayat_name": r["panchayat_name"],
                     "marks_obtained": r["marks_obtained"]} for r in top],
            "distribution": buckets}
