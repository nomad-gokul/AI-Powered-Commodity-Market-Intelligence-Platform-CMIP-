"""Secret redaction for any free-text that might end up in a log line.

LLMClient never logs prompt or completion content (see tracking.py's
docstring) - the observation it records is metadata only. This utility is
defense-in-depth for the one place vendor-supplied *error* text is still
logged (e.g. a 400 response body that happens to echo back part of the
request): retry/failure warning logs pass the exception message through
here first, so an API key or bearer token accidentally present in an SDK
error string never lands in structured logs.
"""

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"\b(sk|gsk|pk|api)[-_][A-Za-z0-9]{16,}\b")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE)),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
)


def redact_secrets(text: str) -> str:
    redacted = text
    for label, pattern in _PATTERNS:
        redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return redacted
