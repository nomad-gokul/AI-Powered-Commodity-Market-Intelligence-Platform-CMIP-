"""Exception hierarchy for the app.ai package.

Mirrors app.modules.documents.storage.base.StorageError's precedent: this
package is reusable outside the web layer (a future CLI, a batch job, a
different service), so it never imports app.core.exceptions. Callers at the
API boundary (none exist yet - that's a later phase) translate these into
CMIPError subclasses, the same way document upload/service code translates
StorageError today.
"""

from typing import Any


class AIError(Exception):
    """Base class for every error raised by app.ai."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# --- Configuration -----------------------------------------------------


class ConfigurationError(AIError):
    """Raised when a provider or the client is asked to construct itself
    from invalid or incomplete configuration (unknown provider name,
    missing API key, unknown model). Raised eagerly at construction time,
    never lazily on first use - see app.ai.providers.factory."""


# --- Provider errors -----------------------------------------------------
#
# Providers translate SDK-specific exceptions into this taxonomy so that
# LLMClient's retry policy can make a single, provider-agnostic decision
# about what is retryable, instead of every call site needing to know
# Groq's exception types differ from OpenAI's differ from Anthropic's.


class ProviderError(AIError):
    """Base class for an LLM provider call failure."""


class ProviderRateLimitError(ProviderError):
    """The provider rejected the request due to rate limiting. Retryable."""


class ProviderTimeoutError(ProviderError):
    """The provider call did not complete within the configured timeout.
    Retryable."""


class ProviderUnavailableError(ProviderError):
    """The provider (or network path to it) is unreachable. Retryable."""


class ProviderAuthError(ProviderError):
    """The provider rejected the request's credentials. NOT retryable -
    retrying with the same key will fail identically every time."""


class ProviderInvalidRequestError(ProviderError):
    """The provider rejected the request as malformed (bad model name,
    invalid parameters). NOT retryable for the same reason as auth
    errors."""


RETRYABLE_PROVIDER_ERRORS: tuple[type[ProviderError], ...] = (
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


# --- Prompt registry -----------------------------------------------------


class PromptAlreadyRegisteredError(AIError):
    """Raised when registering a (name, version) pair that already exists.
    Versions are immutable - re-registering the same key, even with
    identical content, is rejected so callers are never surprised about
    which registration order determined the persisted content."""


class PromptNotFoundError(AIError):
    """Raised when no PromptPackage is registered under the requested
    name (and version, if given)."""


# --- Structured output -----------------------------------------------------


class StructuredOutputError(AIError):
    """Raised when a response still fails Pydantic validation after every
    configured retry attempt has been exhausted."""


# --- Engine / agent errors -----------------------------------------------------


class AgentExecutionError(AIError):
    """Raised when an agent's run() raises and its retry policy has been
    exhausted."""


class AgentTimeoutError(AIError):
    """Raised when an agent's run() does not complete within its step
    timeout, after its retry policy has been exhausted."""


class EngineCancelledError(AIError):
    """Raised when an engine run is cancelled via its CancellationToken."""
