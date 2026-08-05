"""Unit tests for RerankerService: signal normalization, weighted fusion
over partial signals, and stable sort/rank assignment."""

import pytest
from shared.retrieval_contracts import RerankSignals, RetrievalCandidate

from ai_service.retrieval.reranker import RerankerService, get_reranker_service


def _candidate(source_id: str, **signal_overrides: object) -> RetrievalCandidate:
    return RetrievalCandidate(
        source_type="document_chunk",
        source_id=source_id,
        retrieval_method="hybrid",
        score=0.0,
        signals=RerankSignals(**signal_overrides),  # type: ignore[arg-type]
    )


class TestScore:
    def test_no_signals_scores_zero(self) -> None:
        reranker = RerankerService()
        assert reranker.score(RerankSignals()) == 0.0

    def test_single_perfect_signal_scores_at_its_normalized_ceiling(self) -> None:
        reranker = RerankerService()
        score = reranker.score(RerankSignals(vector_similarity=1.0))
        assert score == pytest.approx(1.0)

    def test_missing_signals_do_not_drag_down_the_average(self) -> None:
        """A candidate with only vector_similarity=1.0 present should
        score identically to one with vector_similarity=1.0 AND every
        other signal also at 1.0 - missing signals are excluded from the
        weighted average, not treated as zero."""
        reranker = RerankerService()
        only_vector = reranker.score(RerankSignals(vector_similarity=1.0))
        all_perfect = reranker.score(
            RerankSignals(
                vector_similarity=1.0,
                bm25_score=1_000_000.0,  # squashes to ~1.0
                graph_distance=0,
                entity_trust=1.0,
                relationship_confidence=1.0,
                recency=1.0,
                document_quality=1.0,
            )
        )
        assert only_vector == pytest.approx(1.0)
        assert all_perfect == pytest.approx(1.0, abs=0.01)

    def test_graph_distance_zero_scores_higher_than_far_hop(self) -> None:
        reranker = RerankerService()
        close = reranker.score(RerankSignals(graph_distance=0))
        far = reranker.score(RerankSignals(graph_distance=5))
        assert close > far

    def test_bm25_score_is_squashed_not_left_unbounded(self) -> None:
        reranker = RerankerService()
        score = reranker.score(RerankSignals(bm25_score=1000.0))
        assert 0.0 < score < 1.0

    def test_out_of_range_values_are_clamped(self) -> None:
        reranker = RerankerService()
        score = reranker.score(RerankSignals(entity_trust=5.0))
        assert score <= 1.0


class TestRerank:
    def test_sorts_descending_by_rerank_score(self) -> None:
        reranker = RerankerService()
        low = _candidate("low", vector_similarity=0.1)
        high = _candidate("high", vector_similarity=0.9)
        ranked = reranker.rerank([low, high])
        assert [c.source_id for c in ranked] == ["high", "low"]

    def test_assigns_sequential_final_rank_starting_at_one(self) -> None:
        reranker = RerankerService()
        ranked = reranker.rerank(
            [_candidate("a", vector_similarity=0.5), _candidate("b", vector_similarity=0.9)]
        )
        assert [c.final_rank for c in ranked] == [1, 2]

    def test_does_not_mutate_input_candidates(self) -> None:
        reranker = RerankerService()
        original = _candidate("a", vector_similarity=0.5)
        reranker.rerank([original])
        assert original.rerank_score is None
        assert original.final_rank is None

    def test_empty_input_returns_empty_list(self) -> None:
        assert RerankerService().rerank([]) == []


class TestGetRerankerService:
    def test_returns_cached_singleton(self) -> None:
        assert get_reranker_service() is get_reranker_service()
