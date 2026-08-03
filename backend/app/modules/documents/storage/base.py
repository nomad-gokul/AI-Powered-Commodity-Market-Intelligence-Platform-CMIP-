"""StorageProvider abstraction.

The pipeline, service, and API layers depend on this interface only, never
on a concrete provider - swapping local disk for S3 (or, later, Azure Blob
or GCS) is a config change (STORAGE_PROVIDER=s3), not a code change. Every
method is async and streaming-capable so a multi-hundred-MB report never
has to be held fully in memory.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class StorageError(Exception):
    """Raised by a StorageProvider on backend failure (not found, denied,
    unreachable). Callers translate this into a CMIPError at the service
    boundary; storage implementations never import app.core.exceptions,
    keeping this package usable outside the web layer."""


class StorageProvider(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        """Write `data` to `key`, replacing any existing object."""
        ...

    @abstractmethod
    async def stream_upload(
        self, key: str, stream: AsyncIterator[bytes], *, content_type: str
    ) -> int:
        """Write a stream to `key` without buffering it fully in memory.

        Returns the total number of bytes written.
        """
        ...

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """Read the full object into memory. Only safe for known-small
        objects (e.g. re-reading a page image during OCR) - use
        stream_download for anything that could be large."""
        ...

    @abstractmethod
    def stream_download(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """Yield the object's bytes in chunks without loading it fully into
        memory. Raises StorageError if the key does not exist."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the object. Idempotent: deleting a missing key is not an
        error, matching S3 DeleteObject semantics."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def signed_url(self, key: str, *, expires_in: int) -> str:
        """A time-limited URL a client can use to fetch the object directly,
        without an app-issued bearer token."""
        ...
