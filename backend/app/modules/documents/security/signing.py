"""HMAC signing for local-storage signed URLs.

LocalStorageProvider has no native signed-URL concept the way S3 does, so
this issues a time-limited HMAC token instead, verified by the
`/documents/files/{key}` route without requiring an app bearer token -
the same trust model as an S3 presigned URL (possession of the URL is
sufficient), just implemented ourselves.
"""

import hashlib
import hmac
import time


def sign_storage_key(key: str, expires_at: int, *, secret: str) -> str:
    message = f"{key}:{expires_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_storage_key_signature(
    key: str, expires_at: int, signature: str, *, secret: str
) -> bool:
    if expires_at < int(time.time()):
        return False
    expected = sign_storage_key(key, expires_at, secret=secret)
    return hmac.compare_digest(expected, signature)
