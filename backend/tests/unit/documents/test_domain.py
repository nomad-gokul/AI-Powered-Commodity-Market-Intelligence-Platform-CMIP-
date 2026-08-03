"""Unit tests for the documents module's pure business rules - no database,
no storage, no network."""

import pytest

from app.modules.documents.domain import (
    QuotaExceededDomainError,
    UploadCandidate,
    UploadRejectedError,
    UploadValidator,
    check_duplicate,
    check_quota,
    extract_extension,
    generate_storage_filename,
    sanitize_display_filename,
)


class TestExtractExtension:
    def test_extracts_lowercase_extension(self) -> None:
        assert extract_extension("Report.PDF") == ".pdf"

    def test_no_extension_returns_empty_string(self) -> None:
        assert extract_extension("README") == ""

    def test_leading_dot_is_not_an_extension(self) -> None:
        assert extract_extension(".gitignore") == ""

    def test_trailing_dot_returns_empty_string(self) -> None:
        assert extract_extension("file.") == ""


class TestSanitizeDisplayFilename:
    def test_safe_filename_is_unchanged(self) -> None:
        assert sanitize_display_filename("Platts Dated Brent.pdf") == "Platts Dated Brent.pdf"

    def test_path_separators_are_replaced(self) -> None:
        # ".." itself is fine in a display-only name (see docstring: this
        # is never used to build a path) - the property that matters is no
        # path separator survives, which is what makes it display-only-safe.
        result = sanitize_display_filename("../../etc/passwd")
        assert "/" not in result

    def test_null_bytes_are_stripped(self) -> None:
        assert "\x00" not in sanitize_display_filename("evil\x00.pdf")

    def test_empty_filename_falls_back_to_placeholder(self) -> None:
        assert sanitize_display_filename("   ") == "upload"


class TestGenerateStorageFilename:
    def test_preserves_extension(self) -> None:
        assert generate_storage_filename(".pdf").endswith(".pdf")

    def test_is_unique_per_call(self) -> None:
        assert generate_storage_filename(".pdf") != generate_storage_filename(".pdf")

    def test_ignores_client_supplied_name_entirely(self) -> None:
        # There is no original_filename parameter at all - this is the point.
        name = generate_storage_filename(".pdf")
        assert "/" not in name
        assert ".." not in name


class TestUploadValidator:
    def _validator(self, **overrides: object) -> UploadValidator:
        defaults: dict[str, object] = {
            "allowed_extensions": [".pdf", ".png"],
            "max_file_size_bytes": 1024,
        }
        defaults.update(overrides)
        return UploadValidator(**defaults)  # type: ignore[arg-type]

    def test_accepts_matching_extension_and_mime(self) -> None:
        validator = self._validator()
        candidate = UploadCandidate(original_filename="report.pdf", mime_type="application/pdf")
        assert validator.validate_filename_and_mime(candidate) == ".pdf"

    def test_rejects_disallowed_extension(self) -> None:
        validator = self._validator()
        candidate = UploadCandidate(original_filename="report.exe", mime_type="application/pdf")
        with pytest.raises(UploadRejectedError, match="not allowed"):
            validator.validate_filename_and_mime(candidate)

    def test_rejects_mime_extension_mismatch(self) -> None:
        """A renamed file (e.g. malware.exe -> malware.pdf) is caught here."""
        validator = self._validator()
        candidate = UploadCandidate(
            original_filename="malware.pdf", mime_type="application/x-msdownload"
        )
        with pytest.raises(UploadRejectedError, match="does not match"):
            validator.validate_filename_and_mime(candidate)

    def test_rejects_empty_filename(self) -> None:
        validator = self._validator()
        candidate = UploadCandidate(original_filename="   ", mime_type="application/pdf")
        with pytest.raises(UploadRejectedError, match="empty"):
            validator.validate_filename_and_mime(candidate)

    def test_validate_size_accepts_within_limit(self) -> None:
        self._validator().validate_size(1024)

    def test_validate_size_rejects_zero(self) -> None:
        with pytest.raises(UploadRejectedError, match="empty"):
            self._validator().validate_size(0)

    def test_validate_size_rejects_over_limit(self) -> None:
        with pytest.raises(UploadRejectedError, match="exceeds"):
            self._validator().validate_size(1025)

    def test_max_file_size_bytes_is_exposed_for_streaming_guards(self) -> None:
        assert self._validator(max_file_size_bytes=999).max_file_size_bytes == 999


class TestCheckDuplicate:
    def test_no_existing_hash_is_not_a_duplicate(self) -> None:
        assert check_duplicate("abc123", None) is False

    def test_matching_hash_is_a_duplicate(self) -> None:
        assert check_duplicate("abc123", "abc123") is True

    def test_different_hash_is_not_a_duplicate(self) -> None:
        assert check_duplicate("abc123", "xyz789") is False


class TestCheckQuota:
    def test_unlimited_quota_never_raises(self) -> None:
        check_quota(current_count=10_000, max_documents=None)

    def test_under_quota_does_not_raise(self) -> None:
        check_quota(current_count=4, max_documents=5)

    def test_at_quota_raises(self) -> None:
        with pytest.raises(QuotaExceededDomainError):
            check_quota(current_count=5, max_documents=5)

    def test_over_quota_raises(self) -> None:
        with pytest.raises(QuotaExceededDomainError):
            check_quota(current_count=6, max_documents=5)
