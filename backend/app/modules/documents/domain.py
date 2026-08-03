"""Pure business rules for document ingestion: upload validation, duplicate
detection, and quota enforcement. Zero SQLAlchemy/FastAPI/storage imports -
the service layer supplies live data (an existing hash match, a current
document count) and calls into this module to decide what to do with it.
Unit tested with no database at all (tests/unit/documents/test_domain.py).
"""

import re
import uuid
from dataclasses import dataclass

# Extension -> the MIME type(s) a genuine file of that type reports. Used to
# catch the common spoofing case (a renamed .exe uploaded as "report.pdf")
# without needing full content sniffing for this phase.
_EXTENSION_MIME_MAP: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".tiff": frozenset({"image/tiff"}),
}

_UNSAFE_FILENAME_CHAR_RE = re.compile(r"[^A-Za-z0-9 ._-]")
_MAX_ORIGINAL_FILENAME_LENGTH = 512


class UploadRejectedError(Exception):
    """The candidate file itself is invalid (bad type, size, empty).

    Mapped to UnprocessableUploadError (422) by the service layer.
    """


class QuotaExceededDomainError(Exception):
    """The uploader has hit their document quota.

    Mapped to QuotaExceededError (403) by the service layer.
    """


@dataclass(frozen=True)
class UploadCandidate:
    """Framework-free projection of an incoming upload's declared metadata,
    known before any bytes are read - file_size is not part of this: with a
    streamed multipart upload, the real size is only known once the body
    has been fully consumed, so it is validated separately (see
    UploadValidator.validate_size) against bytes actually written to
    storage, not a client-declared (and therefore spoofable) value."""

    original_filename: str
    mime_type: str


def extract_extension(filename: str) -> str:
    """Lowercased extension including the leading dot, or "" if none."""
    idx = filename.rfind(".")
    if idx <= 0 or idx == len(filename) - 1:
        return ""
    return filename[idx:].lower()


def sanitize_display_filename(original_filename: str) -> str:
    """Best-effort readable filename for API responses/audit logs only.

    This is never used to construct a storage path - see
    generate_storage_filename() for why storage keys are wholly
    server-generated instead of sanitize-and-reuse.
    """
    name = original_filename.strip().replace("\x00", "")[:_MAX_ORIGINAL_FILENAME_LENGTH]
    name = _UNSAFE_FILENAME_CHAR_RE.sub("_", name)
    return name or "upload"


def generate_storage_filename(extension: str) -> str:
    """A server-generated, collision-proof filename.

    Deliberately ignores the client-supplied filename entirely rather than
    sanitizing and reusing it: a blocklist-based sanitizer can always miss a
    case, while a wholly server-generated name makes directory traversal via
    the filename structurally impossible. `original_filename` is preserved
    separately (sanitize_display_filename()) for display only.
    """
    return f"{uuid.uuid4().hex}{extension}"


class UploadValidator:
    """Validates an incoming upload against the configured allow-list and
    size limit. Raises UploadRejectedError on any violation."""

    def __init__(self, *, allowed_extensions: list[str], max_file_size_bytes: int) -> None:
        self._allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self._max_file_size_bytes = max_file_size_bytes

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_bytes

    def validate_filename_and_mime(self, candidate: UploadCandidate) -> str:
        """Returns the validated, normalized extension."""
        if not candidate.original_filename.strip():
            raise UploadRejectedError("Filename must not be empty")

        extension = extract_extension(candidate.original_filename)
        if extension not in self._allowed_extensions:
            allowed = ", ".join(sorted(self._allowed_extensions))
            raise UploadRejectedError(
                f"File extension '{extension or '(none)'}' is not allowed. Allowed: {allowed}"
            )

        expected_mime_types = _EXTENSION_MIME_MAP.get(extension)
        if expected_mime_types is None:
            raise UploadRejectedError(f"Unsupported file extension '{extension}'")
        if candidate.mime_type not in expected_mime_types:
            raise UploadRejectedError(
                f"Declared MIME type '{candidate.mime_type}' does not match "
                f"extension '{extension}' (expected one of {sorted(expected_mime_types)})"
            )

        return extension

    def validate_size(self, file_size: int) -> None:
        """Checked against the actual number of bytes written to storage,
        not a client-declared Content-Length - see UploadCandidate."""
        if file_size <= 0:
            raise UploadRejectedError("Uploaded file is empty")
        if file_size > self._max_file_size_bytes:
            raise UploadRejectedError(
                f"File size {file_size} bytes exceeds the maximum of "
                f"{self._max_file_size_bytes} bytes"
            )


def check_duplicate(candidate_hash: str, existing_hash: str | None) -> bool:
    """True if a non-deleted document with this hash already exists."""
    return existing_hash is not None and candidate_hash == existing_hash


def check_quota(*, current_count: int, max_documents: int | None) -> None:
    """Raises QuotaExceededDomainError if the uploader is at or over quota.

    max_documents=None means unlimited (the Phase 2 default) - quotas are
    opt-in per deployment via CMIP_UPLOAD_MAX_DOCUMENTS_PER_USER.
    """
    if max_documents is not None and current_count >= max_documents:
        raise QuotaExceededDomainError(
            f"Upload quota exceeded: {current_count}/{max_documents} documents"
        )
