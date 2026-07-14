"""
Media uploads (sponsor logos) to the public Cloud Storage bucket.
Bucket has uniform bucket-level access + allUsers:objectViewer, so uploaded
objects are publicly readable at storage.googleapis.com/<bucket>/<name>.
"""
import os
import uuid
from google.cloud import storage

_BUCKET = os.environ.get("MEDIA_BUCKET", "udaan-platform-260701-udaan-papers")
_client = storage.Client()

_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg"}


def is_supported(content_type: str) -> bool:
    return content_type in _EXT


def upload_logo(data: bytes, content_type: str) -> str:
    ext = _EXT.get(content_type, "img")
    name = f"sponsor-logos/{uuid.uuid4().hex}.{ext}"
    blob = _client.bucket(_BUCKET).blob(name)
    blob.cache_control = "public, max-age=86400"
    blob.upload_from_string(data, content_type=content_type)
    return f"https://storage.googleapis.com/{_BUCKET}/{name}"
