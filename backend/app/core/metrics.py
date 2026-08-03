"""Prometheus metrics.

Metric objects are process-global (the prometheus_client convention) and
are updated at their actual call sites in the upload service and worker
pipeline - not decoratively. queue_length is the one exception: nothing in
the process naturally tracks queue depth between scrapes, so it's computed
on demand at scrape time via a Redis LLEN on ARQ's queue key (see
GET /metrics in app.main).
"""

from prometheus_client import Counter, Gauge, Histogram

upload_duration_seconds = Histogram(
    "cmip_upload_duration_seconds", "Time spent handling a document upload request"
)
ocr_duration_seconds = Histogram(
    "cmip_ocr_duration_seconds", "Time spent running OCR on a single page or image"
)
extraction_duration_seconds = Histogram(
    "cmip_extraction_duration_seconds", "Time spent on text/table extraction for one document"
)
processing_duration_seconds = Histogram(
    "cmip_processing_duration_seconds", "End-to-end duration of a document ingestion job"
)
documents_processed_total = Counter(
    "cmip_documents_processed_total", "Documents that finished a processing job", ["status"]
)
worker_failures_total = Counter(
    "cmip_worker_failures_total", "Processing job failures (including ones that will retry)",
    ["job_type"],
)
job_retries_total = Counter(
    "cmip_job_retries_total", "Processing job retry attempts", ["job_type"]
)
queue_length = Gauge(
    "cmip_queue_length", "Jobs currently queued in the ARQ ingestion queue"
)

# --- AI engine / LLM providers (Phase 3.1) ---
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
