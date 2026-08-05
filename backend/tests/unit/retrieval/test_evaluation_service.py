"""Unit tests for EvaluationService: recall/precision@K computed only
against real recorded judgments, never fabricated for an unjudged query."""

from app.modules.retrieval.evaluation_service import (
    EvaluationService,
    RelevanceJudgment,
    get_evaluation_service,
)


class TestComputeMetrics:
    def test_returns_none_when_no_judgments_recorded(self) -> None:
        service = EvaluationService()
        assert service.compute_metrics("unjudged query", [], k=10) is None

    def test_returns_none_when_no_judgment_is_marked_relevant(self) -> None:
        service = EvaluationService()
        service.record_relevance_judgment(
            RelevanceJudgment(
                query="q", source_type="document_chunk", source_id="c1", relevant=False
            )
        )
        assert service.compute_metrics("q", [("document_chunk", "c1")], k=10) is None

    def test_perfect_retrieval_scores_full_recall_and_precision(self) -> None:
        service = EvaluationService()
        service.record_relevance_judgment(
            RelevanceJudgment(
                query="q", source_type="document_chunk", source_id="c1", relevant=True
            )
        )
        metrics = service.compute_metrics("q", [("document_chunk", "c1")], k=10)
        assert metrics is not None
        assert metrics.recall_at_k == 1.0
        assert metrics.precision_at_k == 1.0

    def test_partial_recall_when_only_some_relevant_items_are_retrieved(self) -> None:
        service = EvaluationService()
        service.record_relevance_judgment(
            RelevanceJudgment(
                query="q", source_type="document_chunk", source_id="c1", relevant=True
            )
        )
        service.record_relevance_judgment(
            RelevanceJudgment(
                query="q", source_type="document_chunk", source_id="c2", relevant=True
            )
        )
        metrics = service.compute_metrics("q", [("document_chunk", "c1")], k=10)
        assert metrics is not None
        assert metrics.recall_at_k == 0.5
        assert metrics.precision_at_k == 1.0

    def test_k_truncates_the_retrieved_list_before_scoring(self) -> None:
        service = EvaluationService()
        service.record_relevance_judgment(
            RelevanceJudgment(
                query="q", source_type="document_chunk", source_id="c2", relevant=True
            )
        )
        retrieved = [("document_chunk", "c1"), ("document_chunk", "c2")]
        metrics = service.compute_metrics("q", retrieved, k=1)
        assert metrics is not None
        assert metrics.recall_at_k == 0.0
        assert metrics.retrieved_count == 1

    def test_irrelevant_retrieved_items_lower_precision(self) -> None:
        service = EvaluationService()
        service.record_relevance_judgment(
            RelevanceJudgment(
                query="q", source_type="document_chunk", source_id="c1", relevant=True
            )
        )
        retrieved = [("document_chunk", "c1"), ("document_chunk", "noise")]
        metrics = service.compute_metrics("q", retrieved, k=10)
        assert metrics is not None
        assert metrics.precision_at_k == 0.5


class TestGetEvaluationService:
    def test_returns_cached_singleton(self) -> None:
        assert get_evaluation_service() is get_evaluation_service()
