"""
Auth: verify Google ID tokens, resolve admin/adult identity.

The frontend signs the user in with Google and sends the ID token as
`Authorization: Bearer <id_token>`. We verify it server-side.
Admins are gated by an allowlist stored in admins/{email}.
"""
import os
from fastapi import Header, HTTPException
from google.oauth2 import id_token
from google.auth.transport import requests as g_requests

from . import db

# Empty default lets the service boot before the OAuth client is created;
# token verification simply fails (401) until GOOGLE_CLIENT_ID is set + redeployed.
_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
_req = g_requests.Request()


def _verify(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token.")
    if not _GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Auth not configured yet (GOOGLE_CLIENT_ID unset).")
    token = authorization.split(" ", 1)[1]
    try:
        info = id_token.verify_oauth2_token(token, _req, _GOOGLE_CLIENT_ID)
    except Exception:
        raise HTTPException(401, "Invalid Google token.")
    return {"uid": info["sub"], "email": info.get("email", "").lower(),
            "name": info.get("name", "")}


def require_adult(authorization: str | None = Header(default=None)) -> dict:
    """Any valid Google user is a valid adult (parent/teacher)."""
    identity = _verify(authorization)
    db.upsert_adult(identity)  # record the adult on first sight
    return identity


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    identity = _verify(authorization)
    if not db.is_admin(identity["email"]):
        raise HTTPException(403, "Not authorized as admin.")
    return identity
