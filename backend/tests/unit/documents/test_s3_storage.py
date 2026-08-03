"""Unit tests for S3StorageProvider, run against moto's ThreadedMotoServer -
a real local HTTP server, not moto's in-process mock_aws.

mock_aws was tried first and does NOT work here: it patches sync botocore's
HTTP layer, and aiobotocore's async response body handling is incompatible
with it (verified: raises `TypeError: object bytes can't be used in
'await' expression` on every call). ThreadedMotoServer is real HTTP end to
end, so it exercises the same code path aioboto3 uses in production.
"""

from collections.abc import AsyncIterator, Iterator

import aioboto3
import pytest
import pytest_asyncio
from moto.server import ThreadedMotoServer

from app.modules.documents.storage.base import StorageError
from app.modules.documents.storage.s3 import S3StorageProvider

BUCKET = "cmip-test-bucket"


@pytest.fixture(scope="module")
def moto_endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(port=0)
    server.start()
    _, port = server.get_host_and_port()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


@pytest_asyncio.fixture
async def provider(moto_endpoint: str) -> AsyncIterator[S3StorageProvider]:
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=moto_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    ) as s3:
        await s3.create_bucket(Bucket=BUCKET)
    yield S3StorageProvider(
        bucket=BUCKET,
        region="us-east-1",
        endpoint_url=moto_endpoint,
        access_key_id="test",
        secret_access_key="test",
    )


async def _stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


class TestUploadAndDownload:
    async def test_upload_then_download_round_trips(self, provider: S3StorageProvider) -> None:
        await provider.upload("doc.pdf", b"hello world", content_type="application/pdf")
        assert await provider.download("doc.pdf") == b"hello world"

    async def test_stream_upload_small_file_returns_correct_total(
        self, provider: S3StorageProvider
    ) -> None:
        total = await provider.stream_upload(
            "small.pdf", _stream([b"abc", b"def"]), content_type="application/pdf"
        )
        assert total == 6
        assert await provider.download("small.pdf") == b"abcdef"

    async def test_stream_upload_large_file_uses_multipart_and_round_trips(
        self, provider: S3StorageProvider
    ) -> None:
        # 6MB across 3 parts - exceeds S3's 5MB single-part minimum, so
        # this genuinely exercises the multipart code path, not just the
        # single-part fallback.
        part = b"x" * (2 * 1024 * 1024)

        async def gen() -> AsyncIterator[bytes]:
            for _ in range(3):
                yield part

        total = await provider.stream_upload(
            "big.bin", gen(), content_type="application/octet-stream"
        )
        assert total == len(part) * 3

        collected = b""
        async for chunk in provider.stream_download("big.bin", chunk_size=1024 * 1024):
            collected += chunk
        assert collected == part * 3

    async def test_download_missing_key_raises_storage_error(
        self, provider: S3StorageProvider
    ) -> None:
        with pytest.raises(StorageError):
            await provider.download("does-not-exist.pdf")


class TestExistsAndDelete:
    async def test_exists_false_for_missing_key(self, provider: S3StorageProvider) -> None:
        assert await provider.exists("nope.pdf") is False

    async def test_exists_true_after_upload(self, provider: S3StorageProvider) -> None:
        await provider.upload("exists.pdf", b"x", content_type="application/pdf")
        assert await provider.exists("exists.pdf") is True

    async def test_delete_removes_object(self, provider: S3StorageProvider) -> None:
        await provider.upload("to-delete.pdf", b"x", content_type="application/pdf")
        await provider.delete("to-delete.pdf")
        assert await provider.exists("to-delete.pdf") is False


class TestSignedUrl:
    async def test_signed_url_is_a_real_presigned_s3_url(self, provider: S3StorageProvider) -> None:
        url = await provider.signed_url("doc.pdf", expires_in=3600)
        assert url.startswith("http")
        assert "doc.pdf" in url
        assert "X-Amz-Signature" in url or "Signature" in url
