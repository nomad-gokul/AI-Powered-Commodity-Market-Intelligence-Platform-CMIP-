"""Programming-time errors for the graph module - never surfaced to the
API layer directly (mirrors trust/exceptions.py: these fire at import
time when built-in rules are registered, not at request time)."""


class RuleAlreadyRegisteredError(Exception):
    """Raised when two relationship rules are registered under the same
    rule_id."""
