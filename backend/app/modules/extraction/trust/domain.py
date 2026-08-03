"""Pure, framework-free domain logic for Phase 3.3's trust layer:
extraction fingerprinting, canonical-id derivation for open-set entity
types, value parsing (dates/numbers), and score math. No I/O, no ORM, no
LLM calls - trivially unit-testable, the same split
app/modules/extraction/domain.py established in Phase 3.2.
"""

import re
from datetime import date

_LEGAL_SUFFIXES = (
    " pvt ltd",
    " pvt. ltd.",
    " private limited",
    " ltd.",
    " ltd",
    " limited",
    " inc.",
    " inc",
    " incorporated",
    " l.l.c.",
    " llc",
    " corp.",
    " corp",
    " corporation",
    " plc",
    " gmbh",
    " s.a.",
    " sa",
    " n.v.",
    " nv",
    " b.v.",
    " bv",
    " co.",
    " co",
)

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Lowercase, strip a trailing corporate suffix, collapse everything
    else to single underscores - "Adani Ports & SEZ Ltd" -> "adani_ports_sez".
    Used to derive a stable canonical_id for open-set entity types
    (companies, organizations, vessels, terminals) that no static alias
    table could ever fully enumerate - see docs/ARCHITECTURE.md's Phase
    3.3 section."""
    text = value.strip().lower()
    for suffix in _LEGAL_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    slug = _SLUG_STRIP_RE.sub("_", text).strip("_")
    return slug or "unknown"


def derive_canonical_id(type_prefix: str, value: str) -> str:
    return f"{type_prefix}:{slugify(value)}"


_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASH_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTH_NAMES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_TEXT_DATE_RE = re.compile(
    r"^(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})$|^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$"
)


def parse_flexible_date(raw: str) -> date | None:
    """Best-effort parse of the date shapes commodity reports actually
    use: ISO (2026-01-12), slash (12/01/2026, assumed D/M/Y - the
    convention most trading-desk reports outside the US use), and
    "12 January 2026" / "January 12, 2026". Returns None rather than
    guessing when the text doesn't match a known shape - an unparseable
    date is exactly what ValidationAgent's date rule should flag, not
    silently coerce into something wrong."""
    text = raw.strip()

    iso_match = _ISO_DATE_RE.match(text)
    if iso_match:
        year, month, day = (int(g) for g in iso_match.groups())
        return _safe_date(year, month, day)

    slash_match = _SLASH_DATE_RE.match(text)
    if slash_match:
        day, month, year = (int(g) for g in slash_match.groups())
        return _safe_date(year, month, day)

    text_match = _TEXT_DATE_RE.match(text)
    if text_match:
        day_first, month_name_first, year_first, month_name_second, day_second, year_second = (
            text_match.groups()
        )
        if day_first is not None:
            day_str, month_name, year_str = day_first, month_name_first, year_first
        else:
            month_name, day_str, year_str = month_name_second, day_second, year_second
        month_number = _MONTH_NAMES.get((month_name or "").lower())
        if month_number is None or day_str is None or year_str is None:
            return None
        return _safe_date(int(year_str), month_number, int(day_str))

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


_NUMERIC_RE = re.compile(r"-?\d+\.?\d*")


def parse_numeric(raw: str) -> float | None:
    """Extracts the first numeric token from free text ("$82.14 per
    barrel" -> 82.14, "1,250 MT" -> 1250.0), stripping thousands
    separators first. Returns None when no numeric token is present."""
    cleaned = raw.replace(",", "")
    match = _NUMERIC_RE.search(cleaned)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def values_equal_within_tolerance(a: float, b: float, *, relative_tolerance: float = 0.05) -> bool:
    if a == b:
        return True
    denominator = max(abs(a), abs(b))
    if denominator == 0:
        return True
    return abs(a - b) / denominator <= relative_tolerance


# Weight applied to a validation rule's pass/fail outcome when
# ConfidenceAgent aggregates an entity's validation_score - a failed
# CRITICAL rule should pull the score down harder than a failed INFO one.
SEVERITY_WEIGHTS: dict[str, float] = {
    "info": 1.0,
    "warning": 1.0,
    "error": 2.0,
    "critical": 3.0,
}


def clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def weighted_average(scores: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted mean of named score components. Weights need not sum to
    1.0 (normalized internally against only the components present in
    `scores`), so a caller can add or drop a dimension without needing to
    hand-rebalance every other weight."""
    total_weight = sum(weights[name] for name in scores)
    if total_weight <= 0:
        return 0.0
    return sum(scores[name] * weights[name] for name in scores) / total_weight
