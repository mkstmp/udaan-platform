"""
Ranking — computed ONCE at publish time and stored on each registration.
Student view, leaderboard, and admin slices all read the same stored numbers.

Standard competition ranking (ties share a rank): rank = 1 + (# with strictly
higher marks in the same class & scope).
"""
from . import db

SCOPES = ("panchayat", "block", "district", "state")


def _rank_maps(regs, scope):
    """Return {registration_id: (rank, of)} for one scope, within class."""
    # group by (class, scope_value); 'state' groups by class only.
    groups = {}
    for r in regs:
        key = (r["class"],) if scope == "state" else (r["class"], r[f"{scope}_name"])
        groups.setdefault(key, []).append(r)

    out = {}
    for key, members in groups.items():
        members_sorted = sorted(members, key=lambda x: x["marks_obtained"], reverse=True)
        of = len(members_sorted)
        for m in members_sorted:
            higher = sum(1 for x in members_sorted if x["marks_obtained"] > m["marks_obtained"])
            out[m["registration_id"]] = (higher + 1, of)
    return out


def compute_and_publish(exam_id: str) -> int:
    regs = db.registrations_with_marks(exam_id)  # only those with marks_obtained set
    if not regs:
        return 0

    maps = {scope: _rank_maps(regs, scope) for scope in SCOPES}

    updates = []
    leaderboard = []
    for r in regs:
        rid = r["registration_id"]
        patch = {"status": "published"}
        for scope in SCOPES:
            rank, of = maps[scope][rid]
            patch[f"rank_{scope}"] = rank
            patch[f"of_{scope}"] = of
        updates.append((rid, patch))

        # Denormalized, PII-free leaderboard row.
        leaderboard.append({
            "exam_id": exam_id,
            "class": r["class"],
            "name": r["student_name"],           # denormalized, non-PII
            "panchayat_name": r["panchayat_name"],
            "block_name": r["block_name"],
            "district_name": r["district_name"],
            "marks_obtained": r["marks_obtained"],
        })

    db.batch_update_registrations(updates)
    db.replace_leaderboard(exam_id, leaderboard)
    db.mark_exam_published(exam_id)
    return len(updates)
