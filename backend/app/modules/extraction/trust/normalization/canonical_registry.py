"""CanonicalRegistry: in-process, alias-based entity resolution.

Loads a JSON reference-data file into an in-memory lookup from normalized
alias -> canonical entry - deterministic, no DB round trip, trivially
unit-testable. Same in-process-registry shape as PromptRegistry
(app/ai/prompts/registry.py) applied to reference data instead of prompt
content: both are "load once at process start, resolve many times."

Extending the alias list is a data-file change + deploy, not a runtime
database write - see docs/ARCHITECTURE.md's Phase 3.3 section for why
that tradeoff was chosen over a database-backed reference table.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalEntry:
    canonical_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalMatch:
    canonical_id: str
    canonical_name: str
    matched_alias: str
    extra: dict[str, Any] = field(default_factory=dict)


def normalize_alias(value: str) -> str:
    """Case/whitespace-insensitive key used for alias lookups."""
    return " ".join(value.strip().lower().split())


class CanonicalRegistry:
    def __init__(self, entries: list[CanonicalEntry]) -> None:
        self._entries = entries
        self._by_alias: dict[str, CanonicalEntry] = {}
        for entry in entries:
            for alias in entry.aliases:
                self._by_alias[normalize_alias(alias)] = entry

    def resolve(self, raw_value: str) -> CanonicalMatch | None:
        entry = self._by_alias.get(normalize_alias(raw_value))
        if entry is None:
            return None
        return CanonicalMatch(
            canonical_id=entry.canonical_id,
            canonical_name=entry.canonical_name,
            matched_alias=raw_value,
            extra=entry.extra,
        )

    def resolve_numeric_prefix(
        self, raw_value: str, *, prefix_length: int
    ) -> CanonicalMatch | None:
        """Best-effort prefix match for hierarchical codes: an 8-digit HS
        code "27101943" resolves against the registered 2-digit chapter
        "27" even though the full 8-digit code was never seeded - the
        canonical registry only needs chapter-level coverage to be useful
        for normalization, not the full ~5,000-line HS nomenclature."""
        digits = "".join(ch for ch in raw_value if ch.isdigit())
        if len(digits) < prefix_length:
            return None
        return self.resolve(digits[:prefix_length])

    def __len__(self) -> int:
        return len(self._entries)
