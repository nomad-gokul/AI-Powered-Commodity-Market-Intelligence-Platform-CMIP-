"""Unit tests for LocalStorageProvider - real filesystem I/O against a
pytest tmp_path, no mocking of the filesystem itself."""

from collections.abc import AsyncIterator

import pytest

from app.modules.documents.storage.base import StorageError
from app.modules.documents.storage.local import LocalStorageProvider


async def _stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


@pytest.fixture
def provider(tmp_path: object) -> LocalStorageProvider:
    return LocalStorageProvider(root_dir=str(tmp_path), signing_secret="test-secret")


class TestUploadAndDownload:
    async def test_upload_then_download_round_trips(self, provider: LocalStorageProvider) -> None:
        await provider.upload("doc.pdf", b"hello world", content_type="application/pdf")
        assert await provider.download("doc.pdf") == b"hello world"

    async def test_stream_upload_returns_total_bytes_written(
        self, provider: LocalStorageProvider
    ) -> None:
        total = await provider.stream_upload(
            "doc.pdf", _stream([b"abc", b"def", b"gh"]), content_type="application/pdf"
        )
        assert total == 8
        assert await provider.download("doc.pdf") == b"abcdefgh"

    async def test_stream_download_yields_all_bytes(self, provider: LocalStorageProvider) -> None:
        await provider.upload("doc.pdf", b"a" * 5000, content_type="application/pdf")
        collected = b""
        async for chunk in provider.stream_download("doc.pdf", chunk_size=1000):
            collected += chunk
        assert collected == b"a" * 5000

    async def test_download_missing_key_raises_storage_error(
        self, provider: LocalStorageProvider
    ) -> None:
        with pytest.raises(StorageError):
            await provider.download("does-not-exist.pdf")

    async def test_upload_overwrites_existing_object(self, provider: LocalStorageProvider) -> None:
        await provider.upload("doc.pdf", b"first", content_type="application/pdf")
        await provider.upload("doc.pdf", b"second", content_type="application/pdf")
        assert await provider.download("doc.pdf") == b"second"


class TestExistsAndDelete:
    async def test_exists_false_for_missing_key(self, provider: LocalStorageProvider) -> None:
        assert await provider.exists("nope.pdf") is False

    async def test_exists_true_after_upload(self, provider: LocalStorageProvider) -> None:
        await provider.upload("doc.pdf", b"x", content_type="application/pdf")
        assert await provider.exists("doc.pdf") is True

    async def test_delete_removes_object(self, provider: LocalStorageProvider) -> None:
        await provider.upload("doc.pdf", b"x", content_type="application/pdf")
        await provider.delete("doc.pdf")
        assert await provider.exists("doc.pdf") is False

    async def test_delete_missing_key_is_idempotent(self, provider: LocalStorageProvider) -> None:
        await provider.delete("never-existed.pdf")  # must not raise


class TestPathTraversalProtection:
    async def test_rejects_key_with_parent_directory_reference(
        self, provider: LocalStorageProvider
    ) -> None:
        with pytest.raises(StorageError):
            await provider.upload("../escape.pdf", b"x", content_type="application/pdf")

    async def test_rejects_absolute_path_key(self, provider: LocalStorageProvider) -> None:
        with pytest.raises(StorageError):
            await provider.upload("/etc/passwd", b"x", content_type="application/pdf")

    async def test_rejects_backslash_key(self, provider: LocalStorageProvider) -> None:
        with pytest.raises(StorageError):
            await provider.upload("..\\escape.pdf", b"x", content_type="application/pdf")

    async def test_rejects_empty_key(self, provider: LocalStorageProvider) -> None:
        with pytest.raises(StorageError):
            await provider.upload("", b"x", content_type="application/pdf")


class TestSignedUrl:
    async def test_signed_url_contains_expiry_and_signature(
        self, provider: LocalStorageProvider
    ) -> None:
        url = await provider.signed_url("doc.pdf", expires_in=3600)
        assert "expires=" in url
        assert "signature=" in url
        assert "doc.pdf" in url
