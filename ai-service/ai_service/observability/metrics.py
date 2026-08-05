"""Prometheus metrics for LLM calls.

Moved out of app.core.metrics (Pre-Phase 5 AI Service Extraction): these
are AI-specific, not general backend metrics, so they belong in
ai-service's own observability package - not duplicated in app.core.metrics
(prometheus_client raises on a duplicate metric name). Metric objects are
process-global (the prometheus_client convention) and register against the
default registry, the same one backend's `GET /metrics` endpoint (see
app.main) already scrapes - no code change needed there, since that
endpoint reads whatever is registered, regardless of which module defined
it.
"""

from prometheus_client import Counter, Histogram

llm_call_duration_seconds = Histogram(
    "cmip_llm_call_duration_seconds",
    "Time spent in a single LLMProvider.generate() call",
    ["provider", "model"],
)
llm_tokens_total = Counter(
    "cmip_llm_tokens_total",
    "Tokens consumed by LLM calls",
    ["provider", "model", "kind"],  # kind: prompt | completion
)
llm_estimated_cost_usd_total = Counter(
    "cmip_llm_estimated_cost_usd_total",
    "Approximate USD cost of LLM calls, from ProviderRegistry reference pricing",
    ["provider", "model"],
)
llm_call_failures_total = Counter(
    "cmip_llm_call_failures_total",
    "LLM calls that failed after LLMClient's retry policy was exhausted",
    ["provider", "model", "error_type"],
)
llm_retries_total = Counter(
    "cmip_llm_retries_total",
    "Retry attempts made by LLMClient across all LLM calls",
    ["provider", "model"],
)

# --- Embeddings & reranking (Phase 5: Knowledge Retrieval Platform) ---

embedding_call_duration_seconds = Histogram(
    "cmip_embedding_call_duration_seconds",
    "Time spent in a single EmbeddingProvider.embed() call",
    ["provider", "model"],
)
embedding_tokens_total = Counter(
    "cmip_embedding_tokens_total", "Tokens consumed by embedding calls", ["provider", "model"]
)
rerank_duration_seconds = Histogram(
    "cmip_rerank_duration_seconds", "Time spent in RerankerService.rerank() for one batch"
)
