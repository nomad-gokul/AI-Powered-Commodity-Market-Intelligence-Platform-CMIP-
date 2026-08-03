"""S3-backed StorageProvider via aioboto3 for genuine async, non-blocking
I/O. stream_upload uses S3's multipart upload API so an arbitrarily large
file is never buffered fully in memory - only one part (>=5MB, S3's
minimum for all but the final part) is held at a time.

Tested against moto's mocked S3 (see tests/unit/documents/test_s3_storage.py)
since this environment has no real AWS account - see docs/ARCHITECTURE.md
for that tradeoff.
"""

from collections.abc import AsyncIterator
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from app.modules.documents.storage.base import StorageError, StorageProvider

_MULTIPART_MIN_PART_SIZE = 5 * 1024 * 1024


class S3StorageProvider(StorageProvider):
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._session = aioboto3.Session()
        client_kwargs: dict[str, Any] = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key_id:
            client_kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            client_kwargs["aws_secret_access_key"] = secret_access_key
        self._client_kwargs = client_kwargs

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def stream_upload(
        self, key: str, stream: AsyncIterator[bytes], *, content_type: str
    ) -> int:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            created = await s3.create_multipart_upload(
                Bucket=self._bucket, Key=key, ContentType=content_type
            )
            upload_id = created["UploadId"]
            parts: list[dict[str, Any]] = []
            part_number = 1
            total = 0
            buffer = bytearray()
            try:
                async for chunk in stream:
                    buffer.extend(chunk)
                    total += len(chunk)
                    if len(buffer) >= _MULTIPART_MIN_PART_SIZE:
                        part = await s3.upload_part(
                            Bucket=self._bucket,
                            Key=key,
                            PartNumber=part_number,
                            UploadId=upload_id,
                            Body=bytes(buffer),
                        )
                        parts.append({"ETag": part["ETag"], "PartNumber": part_number})
                        part_number += 1
                        buffer.clear()

                if total == 0:
                    await s3.abort_multipart_upload(
                        Bucket=self._bucket, Key=key, UploadId=upload_id
                    )
                    await s3.put_object(
                        Bucket=self._bucket, Key=key, Body=b"", ContentType=content_type
                    )
                    return 0

                if buffer or not parts:
                    part = await s3.upload_part(
                        Bucket=self._bucket,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=bytes(buffer),
                    )
                    parts.append({"ETag": part["ETag"], "PartNumber": part_number})

                await s3.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except Exception:
                await s3.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
                raise
            return total

    async def download(self, key: str) -> bytes:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                raise StorageError(f"Object not found: {key!r}") from exc
            # Deliberately NOT `async with response["Body"] as body:` -
            # StreamingBody.__aenter__ proxies to the raw aiohttp
            # ClientResponse it wraps (see aiobotocore.response), so that
            # pattern silently hands back an object with no .read()/
            # .iter_chunks() at all. Verified against a real moto server,
            # not assumed from docs.
            return bytes(await response["Body"].read())

    async def stream_download(
        self, key: str, *, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                raise StorageError(f"Object not found: {key!r}") from exc
            async for chunk in response["Body"].iter_chunks(chunk_size):
                yield chunk

    async def delete(self, key: str) -> None:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in ("404", "NoSuchKey"):
                    return False
                raise
            return True

    async def signed_url(self, key: str, *, expires_in: int) -> str:
        async with self._session.client("s3", **self._client_kwargs) as s3:
            url = await s3.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=expires_in
            )
            return str(url)
