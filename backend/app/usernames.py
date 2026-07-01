"""Username generation: real-name-derived, unique, typeable ASCII."""
import re
import unicodedata


def _asciify(name: str) -> str:
    # Normalize; drop combining marks; keep [A-Za-z0-9], spaces -> underscore.
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"[^A-Za-z0-9\s]", "", n).strip()
    n = re.sub(r"\s+", "_", n)
    return n or "student"


def make_username(full_name: str, exists) -> str:
    """
    `exists(username_lc: str) -> bool` checks Firestore for a taken username.
    Devanagari-only names (which asciify to empty) fall back to 'student'.
    """
    base = _asciify(full_name)
    n = 10
    while True:
        candidate = f"{base}_{n}"
        if not exists(candidate.lower()):
            return candidate
        n += 1
        if n > 9999:  # pathological; extremely unlikely
            raise RuntimeError("username space exhausted for base")
