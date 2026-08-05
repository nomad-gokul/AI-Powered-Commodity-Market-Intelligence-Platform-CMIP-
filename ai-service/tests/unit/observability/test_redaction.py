"""Unit tests for redact_secrets - defense-in-depth for logged error text."""

from ai_service.observability.redaction import redact_secrets


class TestRedactSecrets:
    def test_redacts_api_key_looking_token(self) -> None:
        text = "request failed with key sk-abcdef1234567890abcdef"
        redacted = redact_secrets(text)
        assert "sk-abcdef1234567890abcdef" not in redacted
        assert "[REDACTED_API_KEY]" in redacted

    def test_redacts_bearer_token(self) -> None:
        text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
        redacted = redact_secrets(text)
        assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted
        assert "[REDACTED_BEARER_TOKEN]" in redacted

    def test_redacts_email_address(self) -> None:
        text = "contact user@example.com for support"
        redacted = redact_secrets(text)
        assert "user@example.com" not in redacted
        assert "[REDACTED_EMAIL]" in redacted

    def test_leaves_ordinary_text_unchanged(self) -> None:
        text = "the model returned an empty completion"
        assert redact_secrets(text) == text
