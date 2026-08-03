"""Unit tests for the HMAC signing used by LocalStorageProvider's signed
URLs."""

import time

from app.modules.documents.security.signing import (
    sign_storage_key,
    verify_storage_key_signature,
)

SECRET = "test-signing-secret"


class TestSignAndVerify:
    def test_valid_signature_verifies(self) -> None:
        expires_at = int(time.time()) + 3600
        signature = sign_storage_key("doc.pdf", expires_at, secret=SECRET)
        assert (
            verify_storage_key_signature("doc.pdf", expires_at, signature, secret=SECRET) is True
        )

    def test_expired_signature_fails(self) -> None:
        expires_at = int(time.time()) - 10
        signature = sign_storage_key("doc.pdf", expires_at, secret=SECRET)
        assert (
            verify_storage_key_signature("doc.pdf", expires_at, signature, secret=SECRET) is False
        )

    def test_tampered_key_fails(self) -> None:
        expires_at = int(time.time()) + 3600
        signature = sign_storage_key("doc.pdf", expires_at, secret=SECRET)
        assert (
            verify_storage_key_signature("other.pdf", expires_at, signature, secret=SECRET) is False
        )

    def test_tampered_expiry_fails(self) -> None:
        expires_at = int(time.time()) + 3600
        signature = sign_storage_key("doc.pdf", expires_at, secret=SECRET)
        assert (
            verify_storage_key_signature("doc.pdf", expires_at + 1000, signature, secret=SECRET)
            is False
        )

    def test_wrong_secret_fails(self) -> None:
        expires_at = int(time.time()) + 3600
        signature = sign_storage_key("doc.pdf", expires_at, secret=SECRET)
        assert (
            verify_storage_key_signature("doc.pdf", expires_at, signature, secret="wrong-secret")
            is False
        )

    def test_garbage_signature_fails(self) -> None:
        expires_at = int(time.time()) + 3600
        assert (
            verify_storage_key_signature("doc.pdf", expires_at, "not-a-real-sig", secret=SECRET)
            is False
        )
