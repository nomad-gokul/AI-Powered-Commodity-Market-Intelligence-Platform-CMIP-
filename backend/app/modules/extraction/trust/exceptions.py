"""Exceptions for the trust layer's rule registry - a programming-time
error (duplicate rule_id at import), not an HTTP-facing API error, so
this deliberately does not subclass app.core.exceptions.CMIPError."""


class RuleAlreadyRegisteredError(Exception):
    pass
