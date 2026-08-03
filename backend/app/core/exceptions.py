"""Domain exception hierarchy.

Services and repositories raise these instead of HTTPException so business
logic stays free of HTTP concerns. The handler registered in app.main
translates them into a consistent ApiErrorResponse with the right status.
"""

from typing import Any


class CMIPError(Exception):
    """Base class for all application-raised errors."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(CMIPError):
    status_code = 404
    error_code = "not_found"


class ValidationError(CMIPError):
    status_code = 422
    error_code = "validation_error"


class ConflictError(CMIPError):
    status_code = 409
    error_code = "conflict"


class UnauthorizedError(CMIPError):
    status_code = 401
    error_code = "unauthorized"


class ForbiddenError(CMIPError):
    status_code = 403
    error_code = "forbidden"


class RateLimitExceededError(CMIPError):
    status_code = 429
    error_code = "rate_limit_exceeded"


class UnprocessableUploadError(CMIPError):
    """Raised when an uploaded file fails validation (type, size, content)."""

    status_code = 422
    error_code = "invalid_upload"


class QuotaExceededError(CMIPError):
    status_code = 403
    error_code = "quota_exceeded"
