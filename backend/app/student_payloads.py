"""
Student-facing payload builders.

THE RULE: never return `student` (or `student` minus a few fields) to a
username-authenticated caller. Build the response by copying ONLY the
explicitly-allowlisted keys. A whitelist fails safe — if someone later adds
`aadhaar` or `phone` to the student record, it can never appear here unless
a human adds it to the list below on purpose.

Fields that must NEVER reach a student view or admit card:
    dob, school_name, village_name, village_code,
    any phone number, guardian phone, created_by_email, photo
"""

# What a student sees about their own result. Non-PII / already-public.
RESULT_ALLOWLIST = (
    "name", "class",
    "district_name", "block_name", "panchayat_name",  # coarse location, on leaderboard anyway
)

# What prints on the admit card. Coarse location only (Panchayat granularity),
# NO dob / phone / village / school.
ADMIT_ALLOWLIST = (
    "name", "guardian_name", "class", "username",
    "district_name", "block_name", "panchayat_name",
)


def _pick(src: dict, keys) -> dict:
    return {k: src.get(k) for k in keys}


def student_result_view(student: dict, reg: dict) -> dict:
    view = _pick(student, RESULT_ALLOWLIST)
    view.update({
        "username": student.get("username"),
        "marks_obtained": reg.get("marks_obtained"),
        "total_marks": reg.get("total_marks", 100),
        "ranks": {
            "panchayat": {"rank": reg.get("rank_panchayat"), "of": reg.get("of_panchayat")},
            "block":     {"rank": reg.get("rank_block"),     "of": reg.get("of_block")},
            "district":  {"rank": reg.get("rank_district"),  "of": reg.get("of_district")},
            "state":     {"rank": reg.get("rank_state"),     "of": reg.get("of_state")},
        },
    })
    return view


def admit_card_view(student: dict, reg: dict, exam: dict, center: dict) -> dict:
    card = _pick(student, ADMIT_ALLOWLIST)
    card.update({
        "roll_number": reg.get("roll_number"),
        "center_name": center.get("name") if center else None,
        "exam_name": exam.get("name"),
        "exam_date": exam.get("exam_date"),
        "exam_time": f'{exam.get("exam_start_time","")} – {exam.get("exam_end_time","")}',
        "reporting_time": exam.get("reporting_time", "30 minutes before start"),
        "instructions": (
            "Carry this admit card and a school ID. Bring your own pen/pencil. "
            "No mobile phones inside the hall. Reach 30 minutes before start time."
        ),
    })
    # Defensive assertion: fail loudly in tests/CI if a banned key sneaks in.
    banned = {"dob", "school_name", "village_name", "village_code",
              "phone", "mobile", "guardian_mobile", "created_by_email"}
    leaked = banned & set(card.keys())
    assert not leaked, f"PII leak in admit card: {leaked}"
    return card
