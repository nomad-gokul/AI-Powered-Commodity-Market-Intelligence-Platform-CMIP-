"""Filesystem-backed StorageProvider, for local development and single-node
deployments. Real async file I/O via aiofiles - the event loop is never
blocked by disk reads/writes on large files.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import aiofiles.os

from app.modules.documents.security.signing import sign_storage_key
from app.modules.documents.storage.base import StorageError, StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, *, root_dir: str, signing_secret: str) -> None:
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._signing_secret = signing_secret

    def _resolve(self, key: str) -> Path:
        """Resolve `key` to a path guaranteed to live under the storage
        root. Defense in depth: callers are expected to pass only
        server-generated keys (see domain.generate_storage_filename), but
        this rejects traversal attempts regardless of caller trust."""
        if not key or key.startswith("/") or "\\" in key or ".." in Path(key).parts:
            raise StorageError(f"Unsafe storage key: {key!r}")
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageError(f"Storage key escapes root: {key!r}")
        return candidate

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

    async def stream_upload(
        self, key: str, stream: AsyncIterator[bytes], *, content_type: str
    ) -> int:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        async with aiofiles.open(path, "wb") as f:
            async for chunk in stream:
                await f.write(chunk)
                total += len(chunk)
        return total

    async def download(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise StorageError(f"Object not found: {key!r}")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def stream_download(
        self, key: str, *, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        path = self._resolve(key)
        if not path.is_file():
            raise StorageError(f"Object not found: {key!r}")
        async with aiofiles.open(path, "rb") as f:
            while chunk := await f.read(chunk_size):
                yield chunk

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    async def signed_url(self, key: str, *, expires_in: int) -> str:
        """A local storage provider has no native signed-URL concept, so
        this issues an HMAC-signed, time-limited token verified by
        app.modules.documents.api's `/documents/files/{key}` route -
        see sign_storage_key() for the shared signing logic."""
        expires_at = int(time.time()) + expires_in
        signature = sign_storage_key(key, expires_at, secret=self._signing_secret)
        return f"/api/v1/documents/files/{key}?expires={expires_at}&signature={signature}"
