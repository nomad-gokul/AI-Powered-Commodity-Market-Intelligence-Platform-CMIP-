"""EvaluationService: plumbing for offline IR evaluation (recall/precision
at K) - deliberately NOT computed online from unlabeled retrieval results.

True recall/precision need a set of labeled relevance judgments (query ->
which sources are actually relevant) that doesn't exist anywhere in this
system - fabricating a number from unlabeled data would look real and mean
nothing. This class exposes the two pieces a future offline evaluation job
needs: recording a relevance judgment, and computing recall/precision@K
against however many judgments exist for a query. `compute_metrics`
returns None, never a fabricated 0.0, when no judgments exist - callers
(see app.core.metrics' retrieval_recall_at_k/retrieval_precision_at_k
Gauges) must not set a metric from a None result.

In-memory judgment store: a real deployment would persist judgments in
their own table - out of scope for this phase, which asks for the metric
plumbing, not a full evaluation-harness feature.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RelevanceJudgment:
    query: str
    source_type: str
    source_id: str
    relevant: bool


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    recall_at_k: float
    precision_at_k: float
    judged_count: int
    retrieved_count: int
    k: int


class EvaluationService:
    def __init__(self) -> None:
        self._judgments: dict[str, list[RelevanceJudgment]] = {}

    def record_relevance_judgment(self, judgment: RelevanceJudgment) -> None:
        self._judgments.setdefault(judgment.query, []).append(judgment)

    def compute_metrics(
        self, query: str, retrieved: list[tuple[str, str]], *, k: int
    ) -> EvaluationMetrics | None:
        """`retrieved` is the ranked (source_type, source_id) list already
        truncated to whatever the caller retrieved; only the first `k` are
        considered. Returns None if no relevant-labeled judgments exist
        for `query` - there is nothing meaningful to compute."""
        judgments = self._judgments.get(query)
        if not judgments:
            return None

        relevant_keys = {(j.source_type, j.source_id) for j in judgments if j.relevant}
        if not relevant_keys:
            return None

        top_k = retrieved[:k]
        true_positives = len(set(top_k) & relevant_keys)

        precision = true_positives / len(top_k) if top_k else 0.0
        recall = true_positives / len(relevant_keys)
        return EvaluationMetrics(
            recall_at_k=recall,
            precision_at_k=precision,
            judged_count=len(judgments),
            retrieved_count=len(top_k),
            k=k,
        )


_default_service = EvaluationService()


def get_evaluation_service() -> EvaluationService:
    return _default_service
