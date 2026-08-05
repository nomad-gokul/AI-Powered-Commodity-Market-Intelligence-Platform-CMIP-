"""RerankerService: combines a candidate's raw retrieval signals into one
final score, and sorts a batch of candidates by it.

A weighted, normalized linear scorer over the seven scalar signals
docs/ARCHITECTURE.md's Phase 5 spec lists (vector similarity, BM25,
knowledge-graph distance, entity trust, relationship confidence, recency,
document quality) - not an ML cross-encoder. That is a deliberate,
disclosed scope decision: those signals are exactly what a
learning-to-rank-lite linear fusion needs, and it avoids a heavy new ML
dependency for a phase whose own scope explicitly excludes AI Chat/
Copilot-grade complexity. Pure and stateless: given RerankSignals, it never
touches the database, an LLM, or CMIP's business schema - backend's
HybridRetriever is responsible for populating those signals before calling
this.

Not every candidate carries every signal (a BM25-only chunk hit has no
relationship_confidence; a graph-expansion edge has no bm25_score) - a
missing signal is excluded from both the weighted sum and its weight
total, so the result is always a weighted *average* over the signals that
are actually present, never penalized by absence.
"""

import time

from shared.retrieval_contracts import RerankSignals, RetrievalCandidate

from ai_service.observability.metrics import rerank_duration_seconds

RERANK_WEIGHTS: dict[str, float] = {
    "vector_similarity": 0.30,
    "bm25_score": 0.20,
    "graph_distance": 0.15,
    "entity_trust": 0.15,
    "relationship_confidence": 0.10,
    "recency": 0.05,
    "document_quality": 0.05,
}


class RerankerService:
    def __init__(self, weights: dict[str, float] = RERANK_WEIGHTS) -> None:
        self._weights = weights

    def score(self, signals: RerankSignals) -> float:
        """Combine `signals` into one score in [0, 1]."""
        weighted_sum = 0.0
        weight_total = 0.0
        for field_name in self._weights:
            raw_value = getattr(signals, field_name, None)
            if raw_value is None:
                continue
            normalized = self._normalize(field_name, raw_value)
            weight = self._weights[field_name]
            weighted_sum += normalized * weight
            weight_total += weight

        if weight_total == 0.0:
            return 0.0
        return weighted_sum / weight_total

    def rerank(self, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        """Return `candidates` with `rerank_score` and `final_rank`
        populated, sorted by rerank_score descending. Does not mutate the
        inputs - RetrievalCandidate is a Pydantic model, so this returns
        new instances via model_copy."""
        started = time.monotonic()
        scored = [
            candidate.model_copy(update={"rerank_score": self.score(candidate.signals)})
            for candidate in candidates
        ]
        scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        result = [
            candidate.model_copy(update={"final_rank": index + 1})
            for index, candidate in enumerate(scored)
        ]
        rerank_duration_seconds.observe(time.monotonic() - started)
        return result

    @staticmethod
    def _normalize(field_name: str, value: float) -> float:
        if field_name == "graph_distance":
            # Hop count: 0 hops (the seed entity itself) -> 1.0, further
            # away asymptotically approaches 0. Never negative by
            # construction (a hop count), but clamp defensively anyway.
            return 1.0 / (1.0 + max(0.0, value))
        if field_name == "bm25_score":
            # ts_rank/ts_rank_cd is unbounded above; squash to (0, 1)
            # rather than min-max normalizing across the batch, which
            # would make the same raw score non-reproducible across runs
            # with a different candidate set.
            return value / (1.0 + value) if value >= 0 else 0.0
        # vector_similarity, entity_trust, relationship_confidence,
        # recency, document_quality are all produced already in [0, 1] by
        # their callers - clamp defensively in case a caller's proxy
        # computation drifts outside that range.
        return max(0.0, min(1.0, value))


_default_reranker = RerankerService()


def get_reranker_service() -> RerankerService:
    return _default_reranker
