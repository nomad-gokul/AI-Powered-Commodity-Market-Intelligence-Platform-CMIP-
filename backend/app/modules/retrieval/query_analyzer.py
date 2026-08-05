"""QueryAnalyzer: detects intent, entities, time ranges, and filters in a
free-text retrieval query - deterministically, no LLM call, the same
philosophy Phase 3.3 (trust) and Phase 4 (graph) already established for
everything except the extraction pipeline itself.

Entity detection reuses Phase 3.3's CanonicalRegistry alias-matching
mechanism directly (countries/ports/commodities - static reference data)
plus a `companies` CanonicalRegistry built fresh from live GraphNode rows
(see build_company_registry() - there is no static companies.json, a
company is only "known" once it has appeared in the corpus and been
canonicalized into the graph). Both are plain CanonicalRegistry instances,
so this class is synchronous and has zero database coupling itself - the
DI layer (see api.py's dependency providers) is responsible for building
the companies registry from a fresh GraphNodeRepository query before
constructing a QueryAnalyzer.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from dateutil.relativedelta import relativedelta

from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalEntry,
    CanonicalRegistry,
)
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.graph.models import GraphNode

_MAX_NGRAM = 4
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_QUARTER_RE = re.compile(r"\bQ([1-4])[\s-]?(\d{4})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


class QueryIntent(StrEnum):
    FACTUAL = "factual"
    RELATIONSHIP = "relationship"
    COMPARISON = "comparison"
    LISTING = "listing"
    DEFINITION = "definition"
    UNKNOWN = "unknown"


class QuestionType(StrEnum):
    WHO = "who"
    WHAT = "what"
    WHERE = "where"
    WHEN = "when"
    HOW_MANY = "how_many"
    YES_NO = "yes_no"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class DetectedEntity:
    entity_type: str
    canonical_id: str
    canonical_name: str
    matched_text: str


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: datetime | None
    end: datetime | None
    raw_text: str


@dataclass(frozen=True, slots=True)
class QueryAnalysis:
    query: str
    intent: QueryIntent
    question_type: QuestionType
    entities: list[DetectedEntity] = field(default_factory=list)
    time_range: TimeRange | None = None
    filters: dict[str, Any] = field(default_factory=dict)

    def entities_by_type(self, entity_type: str) -> list[DetectedEntity]:
        return [e for e in self.entities if e.entity_type == entity_type]


def build_company_registry(nodes: list[GraphNode]) -> CanonicalRegistry:
    """Builds a CanonicalRegistry from live graph_nodes rows (node_type
    company), so company detection reuses the exact same alias-matching
    mechanism the static registries use, despite having no static
    companies.json - see this module's docstring."""
    entries = [
        CanonicalEntry(
            canonical_id=node.canonical_id,
            canonical_name=node.display_name,
            aliases=(node.display_name, *node.aliases_json),
        )
        for node in nodes
    ]
    return CanonicalRegistry(entries)


class QueryAnalyzer:
    def __init__(self, *, registries: CanonicalRegistries, companies: CanonicalRegistry) -> None:
        self._sources: tuple[tuple[str, CanonicalRegistry], ...] = (
            ("company", companies),
            ("country", registries.countries),
            ("port", registries.ports),
            ("commodity", registries.commodities),
        )

    def analyze(self, query: str) -> QueryAnalysis:
        entities = self._detect_entities(query)
        time_range = self._detect_time_range(query)
        return QueryAnalysis(
            query=query,
            intent=self._detect_intent(query),
            question_type=self._detect_question_type(query),
            entities=entities,
            time_range=time_range,
            filters=self._build_filters(entities, time_range),
        )

    # -- entity detection --------------------------------------------------

    def _detect_entities(self, query: str) -> list[DetectedEntity]:
        tokens = _TOKEN_RE.findall(query)
        if not tokens:
            return []

        claimed: set[int] = set()
        detected: list[DetectedEntity] = []
        for start, end, span_text in _ngram_spans(tokens, _MAX_NGRAM):
            if any(i in claimed for i in range(start, end)):
                continue
            for entity_type, registry in self._sources:
                match = registry.resolve(span_text)
                if match is not None:
                    detected.append(
                        DetectedEntity(
                            entity_type=entity_type,
                            canonical_id=match.canonical_id,
                            canonical_name=match.canonical_name,
                            matched_text=span_text,
                        )
                    )
                    claimed.update(range(start, end))
                    break
        return detected

    # -- intent / question type --------------------------------------------

    @staticmethod
    def _detect_intent(query: str) -> QueryIntent:
        lowered = query.lower()
        if any(kw in lowered for kw in ("compare", "versus", " vs ", " vs.")):
            return QueryIntent.COMPARISON
        if any(
            kw in lowered
            for kw in ("owns", "owned by", "operates", "relationship", "related to", "connected to")
        ):
            return QueryIntent.RELATIONSHIP
        if any(kw in lowered for kw in ("list ", "list all", "which ", "all of", "every ")):
            return QueryIntent.LISTING
        if any(kw in lowered for kw in ("what is ", "define ", "definition of", "meaning of")):
            return QueryIntent.DEFINITION
        if lowered.strip():
            return QueryIntent.FACTUAL
        return QueryIntent.UNKNOWN

    @staticmethod
    def _detect_question_type(query: str) -> QuestionType:
        lowered = query.strip().lower()
        first_word = lowered.split(" ", 1)[0].rstrip("?") if lowered else ""
        mapping = {
            "who": QuestionType.WHO,
            "what": QuestionType.WHAT,
            "where": QuestionType.WHERE,
            "when": QuestionType.WHEN,
        }
        if first_word in mapping:
            return mapping[first_word]
        if lowered.startswith("how many") or lowered.startswith("how much"):
            return QuestionType.HOW_MANY
        if first_word in ("is", "are", "does", "do", "can", "did", "was", "were"):
            return QuestionType.YES_NO
        return QuestionType.OTHER

    # -- time range ----------------------------------------------------------

    def _detect_time_range(self, query: str) -> TimeRange | None:
        quarter_match = _QUARTER_RE.search(query)
        if quarter_match:
            quarter, year = int(quarter_match.group(1)), int(quarter_match.group(2))
            start = datetime(year, (quarter - 1) * 3 + 1, 1, tzinfo=UTC)
            end = start + relativedelta(months=3)
            return TimeRange(start=start, end=end, raw_text=quarter_match.group(0))

        iso_dates = _ISO_DATE_RE.findall(query)
        if iso_dates:
            start = datetime.fromisoformat(iso_dates[0]).replace(tzinfo=UTC)
            end = (
                datetime.fromisoformat(iso_dates[-1]).replace(tzinfo=UTC)
                if len(iso_dates) > 1
                else start
            )
            return TimeRange(start=start, end=end, raw_text=" to ".join(iso_dates))

        lowered = query.lower()
        now = datetime.now(UTC)
        if "last quarter" in lowered:
            current_quarter_start = datetime(
                now.year, ((now.month - 1) // 3) * 3 + 1, 1, tzinfo=UTC
            )
            start = current_quarter_start - relativedelta(months=3)
            return TimeRange(start=start, end=current_quarter_start, raw_text="last quarter")
        if "last year" in lowered:
            start = datetime(now.year - 1, 1, 1, tzinfo=UTC)
            end = datetime(now.year, 1, 1, tzinfo=UTC)
            return TimeRange(start=start, end=end, raw_text="last year")
        if "this year" in lowered:
            start = datetime(now.year, 1, 1, tzinfo=UTC)
            return TimeRange(start=start, end=None, raw_text="this year")
        if "last month" in lowered:
            end = datetime(now.year, now.month, 1, tzinfo=UTC)
            start = end - relativedelta(months=1)
            return TimeRange(start=start, end=end, raw_text="last month")

        year_match = _YEAR_RE.search(query)
        if year_match:
            year = int(year_match.group(0))
            start = datetime(year, 1, 1, tzinfo=UTC)
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
            return TimeRange(start=start, end=end, raw_text=year_match.group(0))

        return None

    @staticmethod
    def _build_filters(
        entities: list[DetectedEntity], time_range: TimeRange | None
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        for entity_type in ("company", "country", "port", "commodity"):
            matching = [e.canonical_id for e in entities if e.entity_type == entity_type]
            if matching:
                filters[f"{entity_type}_ids"] = matching
        if time_range is not None:
            filters["time_range"] = {
                "start": time_range.start.isoformat() if time_range.start else None,
                "end": time_range.end.isoformat() if time_range.end else None,
            }
        return filters


def _ngram_spans(tokens: list[str], max_n: int) -> list[tuple[int, int, str]]:
    """Every (start, end, joined-text) window from size max_n down to 1,
    longest-first, so scanning in order and skipping already-claimed token
    ranges implements greedy longest-match ("Mundra Port" wins over the
    "Mundra" substring within it)."""
    spans: list[tuple[int, int, str]] = []
    n = len(tokens)
    for size in range(min(max_n, n), 0, -1):
        for start in range(0, n - size + 1):
            end = start + size
            spans.append((start, end, " ".join(tokens[start:end])))
    return spans
