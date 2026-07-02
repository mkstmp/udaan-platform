"""
Seed a self-contained DEMO exam so the leaderboard, student result view, and
admin results screens can be explored before a real exam runs.

Everything is isolated under exam_id = 'udaan-demo' and tagged demo/is_demo, so
it never mixes with real data. Toggle visibility with the admin Test-mode switch
(settings/app.demo_visible) — this script just creates the data.

Run:  GOOGLE_CLOUD_PROJECT=... python scripts/seed_demo.py
Wipe: GOOGLE_CLOUD_PROJECT=... python scripts/seed_demo.py --wipe
"""
import json, os, random, sys, re
from pathlib import Path
from google.cloud import firestore

db = firestore.Client()
EXAM_ID = "udaan-demo"
random.seed(42)

APP = Path(__file__).resolve().parent.parent / "backend" / "app"
GEO = json.loads((APP / "bihar_geo.json").read_text())
PAN = json.loads((APP / "bihar_panchayats.json").read_text())
DCODE = {d["district_name"]: d["district_code"] for d in GEO["districts"]}
BCODE = {(d["district_name"], b["block_name"]): b["block_code"]
         for d in GEO["districts"] for b in d["blocks"]}

# A realistic slice of geography (real LGD names) with enough depth for ranks.
GEOGRAPHY = {
    "Darbhanga": ["Benipur", "Bahadurpur", "Alinagar"],
    "Madhubani": ["Rajnagar", "Benipatti"],
}
FIRST = ["Aarav", "Priya", "Rohit", "Anjali", "Saurabh", "Kajal", "Vikash", "Sneha",
         "Aman", "Pooja", "Rahul", "Nisha", "Deepak", "Ritu", "Manish", "Sonam",
         "Abhishek", "Khushi", "Gaurav", "Preeti", "Suraj", "Neha", "Ankit", "Rani"]
LAST = ["Kumar", "Kumari", "Singh", "Yadav", "Jha", "Mishra", "Paswan", "Thakur"]
CLASSES = [7, 8, 9, 10]


def wipe():
    n = 0
    for coll in ("registrations", "students", "leaderboard"):
        for d in db.collection(coll).where("exam_id", "==", EXAM_ID).stream():
            d.reference.delete(); n += 1
    # students keyed differently (no exam_id) — remove demo ones
    for d in db.collection("students").where("is_demo", "==", True).stream():
        d.reference.delete(); n += 1
    db.collection("exams").document(EXAM_ID).delete()
    print(f"Wiped demo data ({n} docs) + demo exam.")


def build_students():
    students, used = [], set()
    sid = 1
    for dist, blocks in GEOGRAPHY.items():
        for blk in blocks:
            gps = [g["panchayat_name"] for g in PAN.get(dist, {}).get(blk, [])][:3] or [blk]
            gp_codes = {g["panchayat_name"]: g["panchayat_code"]
                        for g in PAN.get(dist, {}).get(blk, [])}
            for pan in gps:
                for cls in CLASSES:
                    for _ in range(random.randint(5, 8)):
                        nm = f"{random.choice(FIRST)} {random.choice(LAST)}"
                        base = re.sub(r"[^A-Za-z]", "_", nm)
                        nn = random.randint(10, 99)
                        while f"{base}_{nn}".lower() in used:
                            nn += 1
                        uname = f"{base}_{nn}"; used.add(uname.lower())
                        marks = max(8, min(100, round(random.gauss(62, 18))))
                        students.append({
                            "student_id": f"DEMO-{sid:04d}", "username": uname,
                            "username_lc": uname.lower(), "name": nm,
                            "guardian_name": f"{random.choice(FIRST)} {random.choice(LAST)}",
                            "class": cls, "medium": random.choice(["Hindi", "English"]),
                            "district_name": dist, "district_code": DCODE.get(dist, "XXX"),
                            "block_name": blk, "block_code": BCODE.get((dist, blk), ""),
                            "panchayat_name": pan, "panchayat_code": gp_codes.get(pan, ""),
                            "is_demo": True, "created_by_uid": "demo",
                            "marks": marks,
                        })
                        sid += 1
    return students


def rank_in(students, scope, s):
    peers = [x for x in students if x["class"] == s["class"]
             and (scope == "state" or x[f"{scope}_name"] == s[f"{scope}_name"])]
    higher = sum(1 for x in peers if x["marks"] > s["marks"])
    return higher + 1, len(peers)


def seed():
    db.collection("exams").document(EXAM_ID).set({
        "exam_id": EXAM_ID, "name": "Udaan Talent Test — DEMO (sample data)",
        "subject": "Mathematics", "exam_date": "2025-11-15",
        "exam_start_time": "10:00 AM", "exam_end_time": "12:00 PM",
        "reporting_time": "9:30 AM", "eligible_classes": CLASSES,
        "status": "completed", "results_published": True, "demo": True,
    })
    students = build_students()
    lb, batch, n = [], db.batch(), 0
    for s in students:
        st_ref = db.collection("students").document(s["student_id"])
        batch.set(st_ref, {k: v for k, v in s.items() if k != "marks"})
        reg = {
            "registration_id": s["student_id"], "exam_id": EXAM_ID,
            "student_id": s["student_id"], "student_name": s["name"], "class": s["class"],
            "center_name": f'{s["panchayat_name"]} Centre',
            "panchayat_name": s["panchayat_name"], "block_name": s["block_name"],
            "district_name": s["district_name"],
            "status": "published", "marks_obtained": s["marks"], "total_marks": 100,
            "is_demo": True,
        }
        for scope in ("panchayat", "block", "district", "state"):
            r, of = rank_in(students, scope, s)
            reg[f"rank_{scope}"], reg[f"of_{scope}"] = r, of
        batch.set(db.collection("registrations").document(s["student_id"]), reg)
        lb.append({"exam_id": EXAM_ID, "class": s["class"], "name": s["name"],
                   "panchayat_name": s["panchayat_name"], "block_name": s["block_name"],
                   "district_name": s["district_name"], "marks_obtained": s["marks"]})
        n += 1
        if n % 400 == 0:
            batch.commit(); batch = db.batch()
    for row in lb:
        batch.set(db.collection("leaderboard").document(), row)
    batch.commit()
    top = sorted(students, key=lambda x: x["marks"], reverse=True)[:5]
    print(f"Seeded demo exam with {len(students)} students.")
    print("Sample usernames to try on Student login / Results:")
    for s in top:
        print(f"   {s['username']}  (Class {s['class']}, {s['marks']}/100, {s['panchayat_name']})")


if __name__ == "__main__":
    if "--wipe" in sys.argv:
        wipe()
    else:
        seed()
