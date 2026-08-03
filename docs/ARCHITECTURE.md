# CMIP Architecture

This document is updated as each phase lands. It currently reflects
**Phase 1 (Foundation)**, **Phase 2 (Document Ingestion)**,
**Phase 3.1 (AI Engine & LLM Infrastructure)**, **Phase 3.2 (Semantic
Document Intelligence)**, **Phase 3.3 (Trust, Validation &
Canonicalization)**, and **Phase 4 (Knowledge Graph & Semantic
Intelligence)**: authentication/RBAC/audit (Phase 1); document
upload, storage, OCR, text/table extraction, and chunking as an async
background pipeline (Phase 2); a provider-agnostic AgentEngine +
LLMProvider abstraction with real Groq/Claude/OpenAI/Ollama
implementations (Phase 3.1); a five-agent SequentialEngine pipeline
that converts a document's chunks into normalized entities and structured
tables - `extraction_runs`, `extracted_entities`, `entity_mentions`,
`extracted_tables`, `table_cells` (Phase 3.2); a second, deterministic
(no LLM call) pipeline that validates, normalizes, and confidence-scores
that output, and queues low-trust entities for human review -
`trust_pipeline_runs`, `validation_results`, `confidence_scores`,
`normalization_results`, `review_queue` (Phase 3.3); and a third,
also-deterministic pipeline that turns those trusted, canonicalized
entities into a persistent, queryable graph of business relationships -
`graph_nodes`, `graph_edges`, `graph_evidence`, `ontology_types`,
`relationship_types`, `graph_build_runs` (Phase 4). See the Roadmap
section for what's next.

## Layering

```
API Layer            - FastAPI routers, request/response DTOs, auth/rate-limit dependencies
Application Services - use-case orchestration, transactions, calls domain + repositories
Domain Layer          - business rules, value objects, invariants (only where they exist)
Repository Layer      - persistence, ORM <-> domain mapping
Database              - PostgreSQL
```

### The domain layer is deliberately uneven

We use a **pragmatic domain layer**, not full DDD: SQLAlchemy models double
as the domain object for simple, rule-free entities (`User`, `Role`,
`AuditLog`). A real `domain.py` with framework-free value objects and pure
functions exists only where a module has actual business rules to protect:

- `app/modules/auth/domain.py` - `PermissionSet` (wildcard permission
  matching) and `evaluate_refresh_token` (expired/revoked/valid
  classification, including the reuse-detection distinction). Both are
  pure functions/classes with zero SQLAlchemy or FastAPI imports, unit
  tested with no database at all (`tests/unit/auth/test_domain.py`).
- `app/modules/documents/domain.py` - `UploadValidator` (extension/MIME
  allow-list, size limit), `generate_storage_filename`/
  `sanitize_display_filename` (the directory-traversal defense), and
  `check_duplicate`/`check_quota`. Same pattern: zero SQLAlchemy/FastAPI/
  storage imports, unit tested standalone
  (`tests/unit/documents/test_domain.py`).

`app/modules/audit/` has no `domain.py` - "write an immutable row" has no
business rule to encapsulate. `Document`/`DocumentVersion`/`ProcessingJob`/
`DocumentChunk` are likewise rule-light persistence entities (the ORM
model doubles as the domain object, same as `User`/`Role`) - the real
rules live in `documents/domain.py` above, not in the models. Later phases
(pricing reconciliation, confidence scoring, premium calculation) will
each get a real domain.py because they have real invariants; CRUD-only
modules won't, to avoid ceremony that protects nothing.

### Cross-module dependency rule, and its one documented exception

Modules depend on other modules' **repositories** (read access), never on
their services or API layers - this keeps business logic owned by exactly
one module. `AuthService` breaks this once, deliberately: it calls
`AuditService.record(...)` directly. This is safe because audit logging is
a write-only, rule-free cross-cutting concern (like logging) - there is no
domain logic in `audit` for `auth` to bypass by going around a repository.
Every other cross-module reference in the codebase should go through a
repository; if you find yourself wanting a second service-to-service call,
that's a sign the two modules should merge or the shared logic should move
into `core`/`common`.

## What's implemented (Phase 1)

### Identity & RBAC

- `users`, `roles`, `user_roles` (many-to-many).
- **RBAC model: embedded permission array**, not a relational
  `permissions`/`role_permissions` table. `roles.permissions` is a
  `text[]` of permission strings (`"documents:upload"`,
  `"audit_logs:read"`, or `"*"` for full access), evaluated by
  `PermissionSet.has()`. Chosen over full relational RBAC because no
  requirement yet needs an admin UI to edit permissions without a code
  deploy; if that need appears, migrating to a `permissions` +
  `role_permissions` table is a data migration, not a redesign - `Role`
  and `PermissionSet.has()` are the only things that would need to change.
- Three seeded roles (`alembic/versions/..._seed_default_roles...py`):
  `admin` (`["*"]`), `analyst` (`["audit_logs:read"]`), `viewer` (`[]`,
  the default for self-registration). Later phases append their own
  permission strings to these roles via new migrations or admin edits -
  the array column never needs a schema change for that.

### Auth tokens

- **Access tokens** are JWTs carrying `sub`, `roles`, and `permissions`,
  so `require_permission(...)` checks need zero DB round trips. Tradeoff:
  a permission change takes up to `ACCESS_TOKEN_EXPIRE_MINUTES` (default
  15) to fully propagate to a user's existing token.
- **Refresh tokens** are opaque high-entropy random strings
  (`secrets.token_urlsafe(48)`), stored **hashed** (SHA-256, not bcrypt -
  see `core/security.py` docstring for why the two secrets get different
  hashing strategies) in `refresh_tokens`, checked against the DB on
  every use, so revocation is immediate.
- **Rotation with reuse detection**: every `/auth/refresh` call revokes
  the presented token and issues a new one. If an already-revoked token
  is presented again (a stolen, already-rotated-out token being replayed),
  every refresh token for that user is revoked and an
  `auth.refresh_token_reuse_detected` audit event is recorded. See
  `tests/integration/test_auth_flow.py::test_refresh_reuse_detection_kills_the_whole_session`.

### Rate limiting

Two-layer plan (only layer 1 exists yet):
1. **App-level, implemented**: `core/rate_limit.py`, a Redis fixed-window
   limiter (`INCR` + `EXPIRE`), applied to `POST /auth/login` to blunt
   credential-stuffing. Business-rule-aware (keyed by route + client IP).
2. **Edge-level, not yet implemented**: coarse IP-based limiting at Nginx,
   added in the hardening phase, protecting routes this app-level limiter
   doesn't cover.

### Audit logging

`AuditService.record(...)` is called **explicitly** from services that
perform sensitive actions (register, login, refresh-reuse-detected) -
not from a blanket "log every request" middleware. A middleware approach
logs noise (every `GET`) alongside signal (a role was revoked) with no way
to tell them apart from the audit trail alone.

### Observability

- Structured JSON logging (`structlog`) in production, readable console
  logs in development.
- `RequestContextMiddleware` binds a `request_id` (from `X-Request-ID` or
  generated) to every log line for the duration of a request, and echoes
  it back in the response header - the foundation the tracing-ready
  requirement builds on later.
- `GET /health` (liveness, no dependency checks) and `GET /health/ready`
  (readiness, checks Postgres + Redis) - split deliberately so a
  transient DB blip doesn't cause an orchestrator to kill a healthy pod.

## What's implemented (Phase 2)

### Processing pipeline

```
Client                API (upload)          Redis (ARQ queue)         Worker process
  │                        │                        │                        │
  ├─ POST /documents/upload ─>                       │                        │
  │                        ├─ stream to storage,     │                        │
  │                        │  hash, validate, dedupe │                        │
  │                        ├─ INSERT documents,      │                        │
  │                        │  document_versions,     │                        │
  │                        │  processing_jobs        │                        │
  │                        ├─ enqueue_job ──────────>│                        │
  │  <── 201 {document, job} ┤                        ├─ pick up job ─────────>│
  │                        │                        │                        ├─ Read File
  │                        │                        │                        ├─ OCR? (native text first)
  │                        │                        │                        ├─ Text Extraction
  │                        │                        │                        ├─ Table Extraction
  │                        │                        │                        ├─ Layout (header/footer)
  │                        │                        │                        ├─ Metadata Extraction
  │                        │                        │                        ├─ Chunk Generation
  │                        │                        │                        ├─ Persist (replace chunks)
  │                        │                        │                        └─ COMPLETED / FAILED
  ├─ GET /processing-jobs/{id} ───────────────────────────────────────────────>│ (polls Postgres, not Redis)
```

Each pipeline stage commits `documents.processing_status` and
`processing_jobs.{current_stage,progress}` before moving to the next, so a
client polling `GET /processing-jobs/{id}` sees live progress, not just a
terminal state.

### Worker architecture

- **ARQ** (`app/worker/`), a Redis-backed async job queue - chosen over
  Celery for a pure-asyncio codebase (no separate sync worker pool/thread
  bridge needed) and over a hand-rolled queue because job persistence,
  retry scheduling, and worker-process management are exactly ARQ's job.
- `app/worker/context.py` builds the storage/OCR/extractor/chunker object
  graph **once** at worker startup (stored in ARQ's `ctx` dict), not
  per-job - matters most for OCR providers where a real engine can be
  expensive to initialize.
- `app/worker/tasks.py::process_document` is the entire pipeline as one
  ARQ job function. It uses `AsyncSessionLocal` directly (not a FastAPI
  dependency - a worker process has no HTTP request to hang a session
  override off).

### Retry, backoff, and dead-letter policy

Retry/backoff/give-up is owned by our own code against
`processing_jobs.retries`/`max_retries` (columns in Postgres, so they
survive a worker restart), **not** by ARQ's built-in retry counter (which
lives in-memory per job attempt). `WorkerSettings.max_tries` is set
generously high (25) purely so ARQ's own ceiling never fires first.

- On failure, `process_document` catches the exception, increments
  `retries`, and either raises `arq.worker.Retry(defer=backoff)` (backoff
  = `PROCESSING_RETRY_BACKOFF_BASE_SECONDS * 2**retries`, i.e. exponential)
  to get ARQ to re-run the job later, or - once `retries >= max_retries` -
  marks the job `FAILED`, the document `FAILED`, and returns normally
  (no further ARQ retry).
- **Dead-letter interface**: rather than standing up a second physical
  queue (ARQ has no native DLQ topic), a permanently failed job's terminal
  state is: `processing_jobs.status = FAILED` + `error_message` + a
  dedicated audit event (`document.processing_dead_lettered`). This is a
  deliberate scope decision - a real DLQ (a separate queue/table) is
  straightforward to add later if failure volume ever justifies it, and
  today's interface (query jobs where `status = 'failed'`) already
  supports operational visibility into what needs attention.
- **Idempotent by construction**: `document_chunks` are deleted and
  re-inserted on every run (never appended), and every status/progress
  field is overwritten, not incremented - so re-running the exact same
  job (our retry, or a user-triggered `POST /documents/{id}/reprocess`)
  converges to the same end state instead of duplicating data. Verified
  directly in `tests/integration/test_worker_pipeline.py`.

### Storage architecture

`StorageProvider` (`app/modules/documents/storage/base.py`) is an ABC with
`upload`/`stream_upload`/`download`/`stream_download`/`delete`/`exists`/
`signed_url`. The rest of the app depends only on this interface -
`STORAGE_PROVIDER=local|s3` in config is the only place a concrete
provider is chosen (`storage/factory.py`).

- **`LocalStorageProvider`** - real async file I/O via `aiofiles`. Storage
  keys are always server-generated (`{uuid4().hex}{extension}`), never
  derived from the client's filename, which makes directory traversal
  structurally impossible rather than relying on a sanitizer blocklist
  that could miss a case.
- **`S3StorageProvider`** - `aioboto3` for genuine async I/O.
  `stream_upload` uses S3's multipart upload API so an arbitrarily large
  file is never buffered fully in memory (only one ≥5MB part at a time).
- **Signed URLs**: S3 uses real presigned URLs. Local storage has no
  native equivalent, so `LocalStorageProvider.signed_url()` issues an
  HMAC-SHA256-signed, time-limited token (`security/signing.py`) verified
  by the `GET /documents/files/{key}` route - deliberately not gated by
  `require_permission`/a bearer token, since possession of a valid
  signature *is* the authorization, the same trust model as an S3
  presigned URL.
- **Docker Compose**: `api` and `worker` share a named volume
  (`documents_data`) mounted at the same path - without it, a file the
  `api` container writes wouldn't be visible to the `worker` container
  that needs to read it back for processing.

#### Why S3 is tested against a real local HTTP server, not `moto.mock_aws`

`moto.mock_aws` patches sync `botocore`'s HTTP layer; `aioboto3`/
`aiobotocore` use a different async HTTP stack, and the two are
incompatible in this environment (verified: every call raised
`TypeError: object bytes can't be used in 'await' expression`, not a
theoretical concern). `tests/unit/documents/test_s3_storage.py` instead
runs `moto.server.ThreadedMotoServer` - a real local HTTP server - and
points `S3StorageProvider` at it via `endpoint_url`, which exercises the
exact same code path production `aioboto3` traffic uses. This is also how
a real bug was caught: `async with response["Body"] as body:` silently
hands back the *raw* `aiohttp.ClientResponse` instead of aiobotocore's
`StreamingBody` (its `__aenter__` proxies to the wrapped object) - `s3.py`
deliberately does not use that pattern; see the comment at its call sites.

### Upload validation & security

- **MIME/extension allow-list** (`UPLOAD_ALLOWED_EXTENSIONS`, default
  `.pdf/.png/.jpg/.jpeg/.tiff`) plus a declared-MIME-must-match-extension
  check, catching the common spoofing case (a renamed executable).
- **Size enforcement during streaming, not after**: the upload stream is
  wrapped in a guard that raises the moment the configured max is
  exceeded, so an oversized upload is rejected without ever being written
  to storage in full.
- **SHA-256 hashing happens in the same streaming pass** as the size
  guard and the storage write - no second read of the body.
- **Duplicate detection**: a second upload with an identical hash (and no
  existing document soft-deleted) is rejected with `409 Conflict`
  referencing the existing document's ID, rather than silently storing a
  second copy.
- **Per-user quotas**: `UPLOAD_MAX_DOCUMENTS_PER_USER` (default
  unlimited) - opt-in, since Phase 2 has no requirement forcing a default
  limit.
- **Virus scanning**: `VirusScanner` ABC (`security/virus_scan.py`), with
  `NullVirusScanner` (always clean) as the Phase 2 implementation. The
  interface takes a *stream*, not bytes, so a real engine (e.g. ClamAV's
  `clamd` INSTREAM protocol) can be swapped in later without forcing the
  caller to buffer a whole file just to satisfy the interface.

### OCR provider strategy

`OCRProvider` ABC (`ocr/base.py`). Native PDF text extraction (PyMuPDF)
always runs first; OCR only runs on a page whose native text is
empty/near-empty (`OCR_MIN_NATIVE_CHARS_PER_PAGE`), or on a standalone
image upload.

- **`TesseractOCRProvider`** is the default and the **only OCR provider
  with real test coverage** in this repository - it's exercised against
  the actual installed `tesseract` binary in both unit
  (`test_tesseract_provider.py`) and integration
  (`test_worker_pipeline.py`) tests.
- **`PaddleOCRProvider`** is implemented for real against the actual
  `paddleocr` package API, available via the optional
  `pip install "cmip-backend[paddleocr]"` extra - but it is **not**
  exercised by this repository's test suite and has **not** been run
  end-to-end in this development environment: `paddlepaddle`'s Windows
  wheel is unreliable to install here. This is a deliberate, explicit
  scope decision (see the class's docstring), not an oversight - verify
  it in a Linux/Docker environment before relying on it in production.

### Extraction & chunking

- **`PDFExtractor`** (PyMuPDF): per-page native text, OCR fallback, PDF
  metadata (title/author/creation date via a hand-parsed `D:YYYYMMDD...`
  format), and `langdetect`-based language detection on the full
  extracted text (skipped for very short documents - too unreliable).
- **`TableExtractor`** (pdfplumber): a second pass over the same PDF
  bytes - pdfplumber's ruling-line/whitespace table detection is
  meaningfully better than PyMuPDF's for the grid-heavy tables common in
  commodity price reports, at the cost of being slower, so PyMuPDF stays
  the primary/faster text extractor.
- **Header/footer detection** (`extraction/layout.py`) is a **documented
  heuristic**, not real layout analysis: a text block within the top/
  bottom 8% of the page height is classified as a header/footer. This
  correctly catches a running masthead or a page-number/copyright line,
  but will misclassify a body paragraph that starts very close to the top
  margin - stated honestly rather than oversold.
- **`DocumentChunker`** (`chunking/chunker.py`): paragraph-boundary-aware,
  configurable `CHUNK_SIZE_TOKENS`/`CHUNK_OVERLAP_TOKENS` (tiktoken
  `cl100k_base`). A paragraph is never split unless it alone exceeds the
  chunk size, in which case it falls back to sentence-boundary splitting,
  and finally to a hard token-level split as a last resort - so chunking
  is guaranteed to terminate. Overlap is carried at paragraph granularity
  (the trailing paragraphs of one chunk are repeated at the start of the
  next). Chunks aren't embedded yet (pgvector arrives with the Phase 3/4
  RAG work) - this phase stores chunk text + metadata only.

### RBAC additions

`5cf29ad980c9_grant_documents_permissions_to_viewer_.py` appends
`documents:upload`/`documents:read` to `viewer` and additionally
`documents:reprocess`/`documents:delete` to `analyst` - `admin` already
has `"*"`. Consistent with Phase 1's coarse resource:action model (no
per-row "own documents only" scoping exists, the same as
`audit_logs:read`).

### Observability additions

- **Prometheus** (`core/metrics.py`, `GET /metrics`): upload duration, OCR
  duration, extraction duration, end-to-end processing duration, documents
  processed (by terminal status), worker failures, job retries, and queue
  length. Every metric except queue length is updated at its real call
  site, not decoratively; queue length is computed on demand at scrape
  time via a Redis `LLEN` on ARQ's queue key, since nothing else in the
  process tracks queue depth between scrapes.

### Deltas from the original Phase 2 spec, made as engineering calls

These were flagged to the user before implementation, not decided
silently:

1. **No `organization_id` on `documents`** - nothing else in the system is
   multi-tenant (`users` has no `organization_id`, RBAC isn't org-scoped),
   so adding it only here would be a dangling, unenforced column.
   Ownership is tracked via `uploaded_by -> users.id`; a real
   `organizations` table is a prerequisite for multi-tenancy, which is a
   cross-cutting change for a future phase, not a Phase 2 add-on.
2. **`document_versions` has no dedicated "upload a new version"
   endpoint** - not in Phase 2's required API list. The table is real and
   auto-populated (version 1 on every upload) rather than left empty and
   unused.
3. **Delete is soft** (`documents.deleted_at`); storage bytes are not
   purged immediately. Coordinating irreversible byte deletion with a
   reversible DB row is a real data-loss risk if done wrong; a retention/
   purge job is future work.
4. **`app/worker/settings.py` (ARQ `WorkerSettings`, `startup`/`shutdown`)
   has no direct test coverage** - `process_document` (the actual
   pipeline logic) is fully covered by calling it directly against a real
   database in `tests/integration/test_worker_pipeline.py`; the thin ARQ
   process-wiring around it would need a live `arq` subprocess to exercise
   and wasn't judged worth the added test complexity for wiring code, not
   business logic. Flagged honestly rather than silently left uncovered.

## What's implemented (Phase 3.1)

Phase 3.1 builds the AI infrastructure every future AI capability
(document extraction, RAG, forecasting, copilots) will sit on top of. It
deliberately does **not** implement any document-facing agent
(`DocumentUnderstandingAgent`, `EntityExtractionAgent`, etc.), the Prompt
Registry, LangGraph, RAG, embeddings, or vector search - those are later
phases. This phase is the engine, not the pipeline.

### Package layout - `backend/app/ai/`

```
app/ai/
|-- engine/          # orchestration - AgentEngine ABC, SequentialEngine, shared types
|-- agents/           # the Agent Protocol only - no concrete agent yet
|-- providers/        # LLMProvider ABC, ProviderCapabilities, ProviderRegistry, the 4 vendor implementations, factory
|-- client/           # LLMClient - the only thing above providers that anything talks to
|-- structured/        # StructuredOutputService - LLMResponse -> Pydantic, with retry-on-invalid
|-- prompts/          # PromptPackage (the data shape; a Prompt Registry to generate them is later)
|-- observability/     # call metadata logging, Prometheus recording, secret redaction
`-- exceptions.py      # AIError hierarchy - independent of app.core.exceptions, same reasoning as StorageError
```

Nothing in `app/ai/` imports from `app/modules/` or `app/main.py` - it is
reusable infrastructure, not wired into the document pipeline yet. That
wiring (an `EntityExtractionAgent` reading a `DocumentChunk` and writing an
`extracted_entities` row) is Phase 3.2's job.

### AgentEngine: orchestration, decoupled from agents

`AgentEngine` (ABC) executes a `Sequence[EngineStep]` against a shared
`AgentContext` and returns an `AgentEngineResult`. `SequentialEngine` is
the only implementation right now and is the default - **`LangGraphEngine`
is deliberately not built this phase** (see "Deltas" below). Per the
user's explicit architectural instruction, **agents know nothing about
orchestration**: `Agent` is a `Protocol` with a single `async def
run(self, context) -> Any` method, imports nothing from `app.ai.engine`,
and has no idea whether it's running sequentially, in a future DAG
backend, or standalone in a test. `EngineStep` is where orchestration
policy actually lives, per agent:

- **Retry** - `RetryPolicy(max_attempts, backoff_base_seconds,
  backoff_multiplier)`, exponential backoff, applied per step.
- **Timeout** - `EngineStep.timeout_seconds` wraps the agent's `run()` in
  `asyncio.wait_for`; a timeout is retried like any other failure and
  recorded as `StepStatus.TIMED_OUT` if retries are exhausted.
- **Conditional branching** - `EngineStep.condition: Callable[[AgentContext],
  bool] | None`. A false condition marks the step `SKIPPED` without
  invoking the agent - e.g. "only run OCR if the document-understanding
  step decided the page is scanned."
- **Failure recovery** - by default, a step whose retries are exhausted
  stops the run (most pipelines are linear dependency chains); setting
  `EngineStep.continue_on_failure=True` lets a genuinely optional,
  best-effort step fail without aborting the rest.
- **Cancellation** - `AgentContext.cancellation_token` (a
  `CancellationToken` wrapping `asyncio.Event`) is checked between every
  step, and after a step completes even if it fired mid-retry, so
  cancelling stops the run at the next safe boundary rather than force-
  killing an in-flight step.
- **Progress reporting** - an optional `async def
  progress_callback(StepProgress)` is invoked on every status transition
  (`RUNNING` -> `SUCCEEDED`/`FAILED`/`TIMED_OUT`/`SKIPPED`/`CANCELLED`),
  each carrying `sequence_index`/`total_steps` for a UI progress bar.
- **Execution context / blackboard** - `AgentContext.state` is a plain
  `dict[str, Any]` that `SequentialEngine` writes each step's output into
  under the agent's `name` after it runs, so a later step's `condition` or
  `run()` can read an earlier step's result. Deliberately untyped: the
  concrete keys belong to whichever agents a later phase registers, not to
  the engine.

### LLMProvider: one abstraction, four real implementations

`LLMProvider` (ABC) exposes exactly one required call -
`generate(LLMRequest) -> LLMResponse` - plus `capabilities`,
`health_check()`, and an optional `stream()` (default raises
`NotImplementedError`; only providers whose `capabilities.supports_streaming`
is `True` override it). Nothing above this layer branches on `if provider
== "groq"` - a capability the engine cares about is a field on
`ProviderCapabilities`, checked once at the call site that needs it.

- **`GroqProvider`** - the development default. Real `groq` SDK, and the
  **one provider with a genuine, credential-backed integration test**
  (`tests/integration/ai/test_groq_live.py`, skipped cleanly via
  `pytest.mark.skipif` when `GROQ_API_KEY` isn't set - it does not touch
  Postgres/Redis/Docker, so it skips even with no services running).
- **`ClaudeProvider`**, **`OpenAIProvider`**, **`OllamaProvider`** - real,
  complete implementations against their official SDKs (`anthropic`,
  `openai`) or, for Ollama (no first-party async Python SDK), direct
  `httpx` calls to its REST API - but **unverified against a live API/
  instance in this environment**. Same precedent PaddleOCR set in Phase 2:
  implemented for real, unit-tested against a mocked SDK client, not
  exercised against the real vendor. If real credentials are supplied
  later, adding their live integration tests is additive.
- **Groq and OpenAI share `_chat_completions_base.py`** - Groq's SDK is a
  fork of `openai-python` exposing an identical
  `chat.completions.create()` shape, so request-building, response-
  parsing, and streaming are implemented once (`ChatCompletionsCompatibleProvider`)
  and only the client construction + exception classes differ per vendor
  (`SDKErrorMap`). This is not itself a registered provider.
- **Claude bridges three real API differences**, documented in its module
  docstring: `system` is a dedicated top-level parameter, not a
  role="system" message; there is no native JSON-schema response format,
  so structured output is achieved by forcing a single synthetic tool call
  and writing the tool's `input` back into `LLMResponse.content` as JSON
  text (so `StructuredOutputService` never needs to know which mechanism
  produced the JSON); and tool results arrive as content *blocks* within a
  message, not a separate `tool_calls` field.
- **Retries live in exactly one place: `LLMClient`.** Every vendor client
  is constructed with `max_retries=0` (Groq/OpenAI/Claude SDKs default to
  2) specifically so the SDK's own retry loop never compounds with
  `LLMClient`'s - two independent retry layers on the same failure would
  multiply worst-case latency for no benefit. Providers only *translate*
  vendor exceptions into a shared taxonomy
  (`ProviderRateLimitError`/`ProviderTimeoutError`/`ProviderUnavailableError`
  are retryable; `ProviderAuthError`/`ProviderInvalidRequestError` are not,
  since retrying them can never succeed) - `LLMClient` is the only thing
  that decides whether and how to retry.
- **`ProviderRegistry`** (`providers/models.py` + `providers/registry.py`)
  is the single source of truth for which models exist per provider -
  context window, max output tokens, per-model `ProviderCapabilities`, and
  best-effort reference pricing (`PRICING_LAST_VERIFIED = "2026-08"`,
  explicitly documented as a point-in-time estimate for cost
  *observability*, not a billing-accurate source - vendors change prices
  without notice). `ProviderFactory.build_provider()` looks up the
  configured model here and **fails fast with `ConfigurationError`** on an
  unknown model or a missing API key, at provider-construction time - not
  three requests later as an opaque vendor 400. Cost estimation itself
  (`ProviderRegistry.estimate_cost_usd`) deliberately never raises, even
  for an unregistered provider/model: it feeds observability bookkeeping
  *after* a call has already succeeded, and a cost-estimation gap must
  never fail a call whose real result the caller already has.

### LLMClient: the only thing above providers anything talks to

`LLMClient.generate()` owns retry policy (above), latency timing, and
recording one `LLMCallObservation` per attempt via
`app.ai.observability.tracking.record_llm_call` - **metadata only**:
provider, model, token counts, latency, retry count, estimated cost,
request/correlation id. Prompt and completion **text is never logged**;
`LLMResponse.raw_response` is a Pydantic field with `exclude=True` for the
same reason (it may hold the vendor SDK's full completion object,
verbatim). The one place vendor *error* text is logged (a retry warning)
is passed through `redact_secrets()` first (`observability/redaction.py`)
as defense-in-depth against an API key or bearer token happening to be
echoed back in an SDK error string.

### StructuredOutputService: the only path to a typed object

Providers never validate Pydantic models. `StructuredOutputService.
generate_structured(request, response_model, max_retries=2)` sets
`LLMRequest.response_format` from `response_model.model_json_schema()`,
calls `LLMClient.generate()`, and validates the result with
`response_model.model_validate_json()`. On invalid JSON or a schema
mismatch, it feeds the model back its own prior (invalid) response plus
the validation error as a corrective follow-up turn and retries, up to
`max_retries` times, before raising `StructuredOutputError`. A manual
`json.loads(response.content)` anywhere in application code is exactly
what this class exists to make unnecessary.

### Configuration

```
LLM_PROVIDER=groq          # groq | claude | openai | ollama - Literal type, invalid value fails fast at Settings() construction
LLM_REQUEST_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=3
LLM_RETRY_BACKOFF_BASE_SECONDS=1.0

GROQ_API_KEY=              # required in production if LLM_PROVIDER=groq (see Settings._validate_llm_config)
GROQ_MODEL=llama-3.3-70b-versatile
CLAUDE_API_KEY=
CLAUDE_MODEL=claude-sonnet-5
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

`Settings._validate_llm_config` (a Pydantic `model_validator`) requires an
API key for the selected provider **only in production** - a developer
switching `LLM_PROVIDER` locally without holding every provider's key is a
normal, unblocked workflow; the equivalent check for whichever provider is
actually requested still happens eagerly at `ProviderFactory` construction
time in every environment, so misconfiguration is never silently deferred
into a request handler.

### Observability

Every `LLMClient.generate()` call - success or failure, first attempt or
retry - produces one structured log line (`llm_call` / `llm_call_retrying`)
and updates five Prometheus metrics defined in `app/core/metrics.py`:
`cmip_llm_call_duration_seconds` (histogram), `cmip_llm_tokens_total`
(counter, labeled `prompt`/`completion`), `cmip_llm_estimated_cost_usd_total`
(counter), `cmip_llm_call_failures_total` (counter, labeled by error type),
and `cmip_llm_retries_total` (counter). Scraped via the existing `GET
/metrics` endpoint from Phase 2 - no new endpoint needed.

### Deltas from the original Phase 3.1 spec, made as engineering calls

Flagged to the user before implementation via `AskUserQuestion`, not
decided silently:

1. **`LangGraphEngine` is not built this phase.** The spec's own
   architecture diagram lists it alongside `SequentialEngine`, but also
   states LangGraph is "an optional orchestration backend, not the core
   architecture." `AgentEngine`'s interface (a `Sequence[EngineStep]` in,
   an `AgentEngineResult` out, agents that import nothing from `engine/`)
   is designed so a `LangGraphEngine` can be added later - as a second
   `AgentEngine` implementation, a new dependency, and its own test suite
   - without touching a single agent or any code that already depends on
   `AgentEngine`.
2. **Provider testing is asymmetric by design.** Groq is real and
   integration-tested (a `GROQ_API_KEY` was supplied for this purpose).
   Claude/OpenAI/Ollama are real, complete implementations against their
   official interfaces, unit-tested against mocked clients, but not
   verified against a live API/instance - no credentials were available
   for those three in this environment. This mirrors the OCR provider
   split in Phase 2 exactly (Tesseract real+tested, PaddleOCR real+
   unverified) and was confirmed with the user via the same kind of
   explicit tradeoff question before writing any provider code.
3. **Pricing data is best-effort, not authoritative.** `providers/models.py`
   ships real, publicly-sourced per-model pricing for cost estimation, not
   fabricated placeholder numbers - but vendor pricing drifts, and this
   module is not wired to any live pricing feed. `PRICING_LAST_VERIFIED`
   exists as a prompt to re-check the numbers periodically, not a
   guarantee.

## What's implemented (Phase 3.2)

Phase 3.2 converts a document's already-ingested chunks into normalized
entities and structured tables via a five-agent `SequentialEngine`
pipeline (Phase 3.1's engine, `app/ai/`) - not RAG, not vector search, not
LangGraph. `ValidationAgent`/`ConfidenceAgent`/`NormalizationAgent` are
explicitly deferred to Phase 3.3: `confidence` and `normalized_value`
throughout this phase are the LLM's own self-reported values from its
structured output, never independently cross-checked.

### The central design decision: grounding in real coordinates

Phase 2's persisted extraction output discards coordinates entirely -
`detect_header_footer` and `TableExtractor` (`app/modules/documents/
extraction/`) both compute bounding boxes internally via PyMuPDF/
pdfplumber and throw them away before returning `ExtractedPage`/
`ExtractedTable`. So grounding Phase 3.2's entities/tables in real data
could not mean reusing Phase 2's persisted objects - it means a fresh,
coordinate-preserving pass over the same source PDF
(`app/modules/extraction/geometry.py`), through different entry points
that retain position:

- `page.get_text("words")` (not `get_text("text")`) for real per-word
  bounding boxes - `PageGeometryExtractor`.
- `page.get_text("dict")`'s block-level output (the same concept Phase
  2's `detect_header_footer` computes and discards) for a compact,
  real-position summary of each page's structure - `PageBlockGeometryExtractor`.
- `page.find_tables()` (not `extract_tables()`, which Phase 2's
  `TableExtractor` uses) for real per-table and per-cell bounding boxes -
  `TableGeometryExtractor`.

No LLM call in this phase ever invents a coordinate. `LayoutAgent` and
`TableExtractionAgent`'s LLM calls are given a summary of already-real
geometry and asked only for semantic interpretation on top of it; entity
bounding boxes are resolved *after* the LLM returns raw_value text, by
matching it against real word spans (`domain.ground_bounding_box` -
best-effort substring matching, returns `None` rather than a wrong guess
when no confident match is found).

### Prompt Registry

`PromptRegistry` (`app/ai/prompts/registry.py`, generic Phase 3.1-adjacent
infra) enforces **immutable versions**: registering the same
`(name, version)` twice raises `PromptAlreadyRegisteredError`, even with
identical content - a prompt version's wording never changes silently.
`PromptRegistry.compute_hash()` hashes only the actual wording (system +
user template), stored on `extraction_runs.prompt_hash` as proof of
exactly what was sent to the model, independent of version labeling.
`app/modules/extraction/prompts/__init__.py`'s `get_extraction_prompt_registry()`
registers this module's four `PromptPackage`s into the shared registry
exactly once per process (wrapped in `lru_cache`, since both the API
process and the worker process need it).

Four prompts are registered: `document_understanding`, `layout_understanding`,
`entity_extraction`, `table_extraction` - one per LLM-calling agent. There
is no prompt for `PersistResultsAgent` (makes no LLM call) or for a
`ValidationAgent`/`ConfidenceAgent`/`NormalizationAgent` (don't exist yet,
Phase 3.3).

### Agent architecture

All five agents implement Phase 3.1's `Agent` Protocol and know nothing
about orchestration - the same rule Phase 3.1 established.

1. **`DocumentUnderstandingAgent`** - one LLM call over a representative
   text sample (the document's first chunks, capped at 8000 chars).
   Returns `DocumentTypeEnum`/commodity/language/business_domain and an
   `extraction_strategy` hint string that `EntityExtractionAgent` reads
   from the blackboard.
2. **`LayoutAgent`** - real geometry (above) plus one LLM call per
   document for reading-order/multi-column classification, grounded in a
   compact summary of that real geometry. Returns both the LLM's semantic
   `LayoutModel` and the real per-word `PageSpanModel` list downstream
   agents ground against.
3. **`EntityExtractionAgent`** - **one LLM call per `DocumentChunk`**, not
   one per document (chosen so entities stay naturally tied to their
   `source_chunk`, confirmed with the user via `AskUserQuestion` before
   implementation). Reads `LayoutAgent`'s real spans from
   `context.state["layout"]` to ground each entity's `bounding_box`.
4. **`TableExtractionAgent`** - reuses Phase 2's already-persisted table
   row-grids (`DocumentChunk.metadata_json["tables"]`, populated by
   `TableExtractor`'s pdfplumber pass in `app/worker/tasks.py`) for
   structure, `TableGeometryExtractor` for real cell bounding boxes, and
   one LLM call *per table* (not per document) purely for title/cell
   normalization - row/column counts and raw cell values are never asked
   of the LLM. Since every chunk on the same page carries an identical
   copy of that page's tables, tables are de-duplicated by page before
   processing (each table interpreted exactly once, not once per chunk on
   its page).
5. **`PersistResultsAgent`** - the pipeline's only non-LLM-calling agent
   (the `Agent` Protocol doesn't require one). Writes accumulated
   entities/mentions/tables/cells to Postgres, delete-then-insert scoped
   to its own `extraction_run_id` - the same idempotency pattern Phase 2
   established for `document_chunks`, so a retried Persist step replaces
   rather than duplicates rows.

`SequentialEngine` writes each step's return value into
`context.state[agent.name]` automatically (Phase 3.1 behavior), which is
how `EntityExtractionAgent` reads `document_understanding`'s
`extraction_strategy` and `layout`'s spans without any agent importing
another agent.

### Extraction pipeline & retry policy

`app/modules/extraction/pipeline.py`'s `build_extraction_pipeline()`
wires all five agents into an `EngineStep` list with a deliberately split
retry policy: `DocumentUnderstandingAgent`/`LayoutAgent` (one LLM call
each) get `RetryPolicy(max_attempts=2)` - a full retry is cheap.
`EntityExtractionAgent`/`TableExtractionAgent` (one call per chunk/table
internally) get `RetryPolicy(max_attempts=1)` - **no** engine-level retry,
deliberately: `LLMClient` (Phase 3.1) already retries each individual call
on transient errors, and `StructuredOutputService` already retries
invalid-schema responses, so a third retry layer re-running the entire
internal loop from scratch on any single failure would be expensive and
mostly redundant. `PersistResultsAgent` is idempotent (above), so it
safely gets `RetryPolicy(max_attempts=2)` too.

`app/worker/tasks.py`'s `run_extraction` (a new ARQ job type, registered
in `WorkerSettings.functions` alongside `process_document`) loads the
`ExtractionRun` and its document's chunks, downloads the source PDF,
builds and runs the pipeline, then aggregates `token_usage`/
`estimated_cost` from every LLM-calling step's own reported usage
(`_aggregate_usage`, via `ProviderRegistry.estimate_cost_usd`) before
marking the run `COMPLETED` or `FAILED`. Unlike `process_document`, there
is **no outer ARQ-level retry**: a fully failed run is marked `FAILED`
terminally and must be re-triggered explicitly (`POST .../extract` again),
which creates a fresh `extraction_run` row - simpler than
`processing_jobs`' dead-letter design because extraction is safely
re-triggerable per-run without redoing OCR/chunking, unlike ingestion
which has no equivalent "just try again" user action.

### API: extraction is its own lifecycle

Confirmed with the user via `AskUserQuestion` before implementation:
extraction has its own trigger/status lifecycle, independent of document
ingestion - matching `extraction_runs` having its own
`status`/`retry_count`/`prompt_version` separate from `processing_jobs`.

- `POST /documents/{id}/extract` (`extraction:trigger` permission) -
  creates a new `PENDING` `ExtractionRun` and enqueues `run_extraction`.
  Rejects (409) if an active run already exists for the document, or if
  the document has no chunks yet (ingestion hasn't completed). 202, not
  200 - matches `POST /documents/{id}/reprocess`'s convention for
  "accepted, runs in the background."
- `GET /extraction-runs/{id}` (`extraction:read`) - run status/metadata.
- `GET /documents/{id}/entities`, `GET /documents/{id}/tables`
  (`extraction:read`) - paginated, scoped to the document's **most
  recent** extraction run (a `SELECT ... WHERE extraction_run_id = (SELECT
  id FROM extraction_runs WHERE document_id = ... ORDER BY created_at
  DESC LIMIT 1)` subquery, `ExtractedEntityRepository`/
  `ExtractedTableRepository.list_for_document`).
- `GET /extraction-tables/{id}` (`extraction:read`) - one table with its
  cells.

RBAC: `viewer` gets `extraction:read` only; `analyst` additionally gets
`extraction:trigger` (mirrors the `documents:upload`/`documents:reprocess`
split from Phase 2); `admin` already has `"*"`.

### Deltas from the original Phase 3.2 spec, made as engineering calls

Flagged to the user before implementation via `AskUserQuestion` (grounding
strategy, extraction granularity, trigger lifecycle), or caught and fixed
during implementation:

1. **A real bounding-box matching bug, caught by its own test.**
   `domain.ground_bounding_box`'s first draft matched a window if
   `target in candidate` **or** `candidate in target` - the second
   direction let a single short span (e.g. "Dated") falsely match before
   a longer, correct window (e.g. "Dated Brent") was ever tried, since
   growing window size is a strictly increasing loop and the first match
   wins. Fixed to only check `target in candidate` (the window's text
   must fully contain the target); the reverse direction was removed.
2. **A real pagination bug, caught before shipping.** `list_entities`/
   `list_tables` initially computed `total_items` from the current page's
   own length instead of a true count query - correct on a single page of
   results, silently wrong on every subsequent page. Fixed by adding
   `count_for_document` to both repositories and returning `(items,
   total)` tuples from the service, matching Phase 2's `DocumentService.
   list_documents` pattern.
3. **A real cross-phase regression, caught only by running the full test
   suite.** `app/worker/context.py`'s `build_worker_context()` was wired
   to construct an `LLMClient` unconditionally - but that function is also
   used by Phase 2's `process_document` tests, which never touch an LLM
   and have no reason to require `GROQ_API_KEY`. The first run of the
   *entire* suite (not any single new test) broke five previously-passing
   Phase 2 integration tests. Fixed by catching `ConfigurationError` in a
   new `_build_llm_client()` helper and falling back to `None` (logged as
   a warning): the worker now always starts, `process_document` is
   unaffected either way, and only an actual `run_extraction` job invoked
   without a configured provider fails - clearly, per-job, not at worker
   startup. A regression test (`tests/unit/worker/test_context.py`) covers
   this directly.
4. **`StructuredOutputService.generate_structured()` was extended, not
   changed.** Phase 3.1's method returns only the validated Pydantic
   object, discarding `LLMUsage` - but this phase needs per-agent usage to
   populate `extraction_runs.token_usage`. Rather than change a frozen
   method's return type, `generate_structured_with_usage()` was added as
   a new method (both now share one private `_generate_and_validate`
   implementation, a pure refactor verified against Phase 3.1's existing
   test suite before adding anything new).
5. **`DocumentChunkRepository.list_for_document()` was added.** Phase 2
   never needed to read back a document's full ordered chunk list (only
   write and count them); Phase 3.2's pipeline does. Purely additive.

## What's implemented (Phase 3.3)

Phase 3.3 does not extract more data - it decides whether Phase 3.2's
already-extracted data can be trusted. `ValidationAgent`, `NormalizationAgent`,
and `ConfidenceAgent` make **no LLM call anywhere**: validation is rule
evaluation over already-persisted rows, confidence is a deterministic
weighted composite, normalization is alias-table/pattern resolution against
a static reference dataset. Using an LLM to grade another LLM's output would
mean grading an unreliable process with another unreliable process; rules
and canonical lookups are auditable and reproducible in a way an LLM
judgment call isn't.

### Pipeline order deviates from the spec's own diagram

Confirmed with the user via `AskUserQuestion` before implementation: the
trust pipeline is its own lifecycle (`POST /extraction-runs/{id}/validate`),
separate from `run_extraction`, mirroring the ingestion-vs-extraction split
Phase 3.2 established - re-normalizing after a canonical-registry update
should not require re-running the LLM.

Within that pipeline, step order is **Validation -> Normalization ->
Confidence -> Review Queue -> Persist**, not the spec's literal
"Validation -> Confidence -> Normalization." That order is not internally
consistent: `confidence_scores.normalization_score` needs normalization's
output to exist before it can be scored. Confidence is deliberately the
pipeline's *last* computed step (before persistence) since it aggregates
everything upstream - validation results, normalization results, and the
entity's own extraction/geometry/layout/table data.

### Rule Engine

`ValidationRuleRegistry` (`app/modules/extraction/trust/rules/registry.py`)
is the "configurable rule registry" the spec asks for - adding or removing
a check is a registration call in `builtin.py`, never a new `if`/`elif`
branch inside `ValidationAgent`. Same in-process-registry shape as
`PromptRegistry`, but without immutable versioning: a buggy rule must be
fixable in place (a prompt's wording is provenance and must never change
silently; a rule's logic is not).

Two rule shapes: `EntityValidationRule` evaluates one entity in isolation
(date, currency, quantity, unit, HS code, Incoterm, exchange rate,
bounding-box geometry - 8 of the 11 named checks); `CrossEntityValidationRule`
evaluates everything a run produced together (duplicates, conflicting
values, table-total reconciliation - the other 3), since a single entity
can't be "a duplicate" in isolation. A cross-entity finding with no single
entity to attribute it to (e.g. a table's stated total not matching the sum
of its rows) carries `entity_id = NULL` - `validation_results.entity_id` is
nullable specifically for this.

Two interpretation calls worth being explicit about, since the spec's
11-item list doesn't map onto Phase 3.2's `EntityType` enum cleanly:
- **"Impossible coordinates"** means bounding-box geometry sanity (negative
  coordinates, a zero/negative-size box, a coordinate beyond any plausible
  page size), not geographic lat/long - there is no GPS-coordinate entity
  type in a commodity-trading extraction taxonomy.
- **"Impossible exchange rates"** applies to `CURRENCY`/`PRICE` entities
  whose raw text looks like an exchange rate (`"83.2/USD"`, `"exchange
  rate: ..."`), not a new `EXCHANGE_RATE` entity type. Adding one would mean
  asking `EntityExtractionAgent` to extract a new kind of thing - exactly
  what this phase's own framing rules out ("the objective is not to extract
  more data") - and would touch Phase 3.2's frozen `EntityType` enum for a
  rare case a regex heuristic already covers.

### Canonical Normalization

`CanonicalRegistry` (`app/modules/extraction/trust/normalization/`) is an
in-process, alias-based lookup loaded once per process from
`reference_data/*.json` - the same in-process-registry pattern
`PromptRegistry` established, applied to reference data instead of prompt
content. Confirmed with the user via `AskUserQuestion`: static in-repo data
files, not a database-backed reference table - deterministic, no DB round
trip on every normalization call, trivially unit-testable; extending the
alias list is a data-file change + deploy, not a runtime write (there is no
UI yet to make "runtime write" meaningful anyway).

`NormalizationAgent` dispatches by entity type into one of four strategies:
- **Closed-set alias lookup** (country, currency, unit, Incoterm) - resolves
  against a seeded reference file or fails cleanly (`normalization_method =
  "unresolved"`, `confidence = 0.0`).
- **Alias lookup with slug fallback** (commodity, port) - tries the alias
  table first, falls back to a derived slug when nothing matches (a real
  report will mention grades/ports the seed data doesn't cover).
- **Slug derivation only** (company, organization, vessel, terminal) - no
  static list could ever enumerate every real company, so
  `domain.derive_canonical_id` (strip a corporate suffix, lowercase, join
  with underscores) is the *primary* strategy, not a fallback - e.g. `"Adani
  Ports & SEZ Ltd"` -> `company:adani_ports_sez`, matching the spec's own
  `company:adani_ports` example almost exactly.
- **Value parsing** (date, quantity, price) - these have no *identity* to
  resolve, only a value to canonicalize: an ISO date string, a `"<value>
  <unit_canonical_id>"` pair (embedded unit resolved against the same unit
  registry), a `"<value> <currency_canonical_id>"` pair. `canonical_id` is
  `NULL` for these three types - the spec's own canonical-id examples
  (`country:US`, `commodity:thermal_coal`, `port:mundra`) are all identity
  types, never a value type.

### Confidence Engine

`ConfidenceAgent` computes 8 named dimensions (`app/modules/extraction/
trust/agents/confidence_agent.py`), all deterministic:

| Dimension | Source |
|---|---|
| `extraction` | The entity's own LLM-reported confidence (Phase 3.2) |
| `geometry` | 1.0 if grounded (`bounding_box` is not `NULL`), 0.4 if not |
| `layout` | Read from `extraction_runs.metadata_json["layout_summary"]` - see below |
| `table` | Average confidence of `ExtractedTable` rows on the entity's page |
| `validation` | Severity-weighted pass ratio, this entity's own (non-cross-entity) findings |
| `consistency` | Severity-weighted pass ratio, this entity's cross-entity findings (duplicate/conflict) - kept **separate** from `validation` so a duplicate-entity warning never double-counts against the same dimension a bad currency code would |
| `normalization` | `NormalizationResult.confidence` for this entity (sibling step, read off `context.state`) |
| `provider` | A static per-provider reliability prior (`groq: 0.85, claude: 0.95, openai: 0.93, ollama: 0.75`, default `0.8`) - explicitly a calibratable starting point, not measured accuracy, documented as such in code |

`overall_score` is a weighted average (validation weighted highest at 0.25,
since it's the most direct "is this actually correct" signal) with a full
`explanation_json` breakdown per entity - never a single flat number.

`confidence_scores`/`normalization_results` use `entity_id` as their own
primary key (spec's field list omits a surrogate `id` for these two tables,
unlike `validation_results`/`review_queue`, which are naturally one-to-many
per entity) - enforced by the schema itself, not an application check.
Two columns beyond the spec's literal 7-column list -
`table_score`/`provider_score` - satisfy `ConfidenceAgent`'s own named
responsibilities ("table", "provider") without dropping either dimension.

**`ExtractionRun.metadata_json` (an existing, previously-empty column) now
carries a compact layout summary** - `run_extraction` (`app/worker/tasks.py`)
writes `{"layout_summary": {"<page>": {"is_multi_column": bool,
"column_count": int}}}` after a successful run, since `LayoutModel` itself
was otherwise held only in-memory for the duration of Phase 3.2's pipeline
and discarded. This is the one integration-required touch to `run_extraction`
- filling in an already-existing, already-unused field, not a schema change.

### Review Queue

`ReviewQueueAgent` (the pipeline's 4th step, before Persist) applies the
spec's four triggers - confidence below threshold, a validation failure,
conflicting values, an unresolved canonical entity - and produces **one**
`review_queue` row per entity, not one per trigger: an entity flagged for
three reasons gets a single row naming all three in `reason`, at the highest
priority among them. `review_queue.entity_id` is required by the schema, so
a table-level finding (`entity_id = NULL`) is recorded in
`validation_results` for audit but cannot itself enter the review queue in
this phase - a documented, disclosed scope boundary, not an oversight; a
future phase adding a nullable `table_id` column would close it.

Backend only, per the spec - `GET /review-queue` (filterable by status),
`GET /review-queue/{id}`, `PATCH /review-queue/{id}` (assign/resolve/
dismiss, reuses `extraction:trigger` since resolving is a mutating action by
the same actor class that triggers extraction/validation).

### Extraction Fingerprint

`compute_extraction_fingerprint()` lives in `app/modules/extraction/domain.py`
(Phase 3.2's own domain module), not in `trust/` - deduplicating a
`trigger_extraction` call is extraction's own lifecycle concern; `trust/`
only ever reads extraction's already-persisted output, it never decides
whether an extraction should re-run. `sha256(document.sha256_hash +
prompt_hash + pipeline_version + provider + model)`, stored on the new
`extraction_runs.extraction_fingerprint` column (nullable - pre-Phase-3.3
runs have none and simply never match). `ExtractionService.trigger_extraction`
checks `ExtractionRunRepository.find_completed_by_fingerprint()` before
creating a new `PENDING` run; an exact match returns the existing
`COMPLETED` run instead of enqueueing the LLM pipeline again.

### Observability

`trust_pipeline_runs` is one table beyond the spec's literal four
(`validation_results`/`confidence_scores`/`normalization_results`/
`review_queue`) - the "run" record this pipeline needs for the same reason
`extraction_runs` exists for Phase 3.2: a place to hang
`started_at`/`completed_at`/`status`/`error_message`/`retry_count` on, and
to let the same `extraction_run` be re-validated multiple times (e.g. after
a canonical-registry update) with each attempt kept as its own historical
row. It also tracks `entities_validated`, `entities_flagged_for_review`, and
`average_confidence` per run - the spec's own observability requirements
("average confidence", "review queue size") need somewhere to land.
`rule_registry_version` (currently `"1.0"`) is recorded per run for the same
provenance reason `prompt_hash` is recorded on `extraction_runs` - so a
historical run can be traced to exactly which rule set produced it.

Nothing sensitive is ever logged: `ValidationFinding.message`,
`review_queue.reason`, and every log line reference entity/run/table ids and
rule names only, never `raw_value`/document content/prompt text.

### Deltas from the original Phase 3.3 spec, made as engineering calls

Flagged to the user before implementation via `AskUserQuestion` (pipeline
lifecycle, canonical reference data source), or made and disclosed during
implementation:

1. **Pipeline step order** (Validation -> Normalization -> Confidence, not
   the spec's literal Validation -> Confidence -> Normalization) - see
   above; the literal order can't produce a `normalization_score`.
2. **`trust_pipeline_runs`** added as observability infrastructure the spec
   doesn't literally list, mirroring `extraction_runs`.
3. **`confidence_scores` gained `table_score`/`provider_score`** beyond the
   spec's literal 7-column list, to satisfy `ConfidenceAgent`'s own named
   responsibilities without dropping either dimension - a superset, not a
   contradiction, of the spec's field list.
4. **`review_queue`/`validation_results` gained `extraction_run_id`**
   (additive, denormalized from `entity_id` -> `extracted_entities.
   extraction_run_id`) so "list this run's review items/validation results"
   doesn't need a join on every request.
5. **"Impossible coordinates" interpreted as bounding-box geometry, not
   GPS** - see Rule Engine above.
6. **"Impossible exchange rates" implemented as a regex-gated rule on
   existing entity types, not a new `EXCHANGE_RATE` `EntityType`** - see
   Rule Engine above; avoids extracting a new kind of data and avoids
   touching Phase 3.2's frozen enum for a rare case.
7. **Company/organization/vessel/terminal canonical ids are slug-derived,
   not alias-looked-up** - an open-set of real-world names could never be
   exhaustively seeded; this was the spec's own implicit intent, confirmed
   by its own `company:adani_ports` example looking exactly like a
   slugified name.
8. **`extraction_fingerprint` computation lives in `app/modules/extraction/
   domain.py`, not `trust/domain.py`** - a deliberate placement call: it's
   extraction's own dedup concern, not a trust-layer concern, even though
   the spec introduced the idea inside this phase.

## What's implemented (Phase 4)

Phase 4 does not extract or validate anything new - it turns Phase 3.3's
already-trusted, already-canonicalized entities into a persistent,
queryable graph of business relationships (ownership, operation,
shipment, location, contractual reference). Like Phase 3.3's three
agents, none of Phase 4's three agents make an LLM call: relationship
extraction is deterministic text-pattern matching over already-linked
data, never an LLM inference. This is not RAG, not embeddings, not
`LangGraphEngine` - those remain later phases, unaffected by this one.

### New module, not nested under `extraction/`

Unlike `trust/`, which lives inside `app/modules/extraction/` because it
is scoped to one `extraction_run_id`, the graph lives at
`app/modules/graph/` as its own top-level module. A graph node
aggregates evidence for one `canonical_id` across *every* document and
extraction run in the corpus - a different aggregate root and a
different lifecycle than either `extraction` or `trust`, so it earns its
own module rather than nesting one layer deeper.

### Relationship evidence: same-chunk co-occurrence + text pattern, by design choice

Confirmed with the user via `AskUserQuestion` before implementation:
relationships are derived only from two entities that were extracted
from the **same document chunk**, connected by a deterministic
regex-matched phrase within a bounded character window
(`MAX_CONNECTOR_CHARS = 80`) between their two mentions'
`character_offset`s. This is the strongest evidence already available
without a schema change - `ExtractedEntity`/`EntityMention` already link
an entity to its source chunk and offset. The alternative considered and
declined - joining `TableCell.raw_value`/`normalized_value` against
`ExtractedEntity` by string equality to mine table-row relationships
(e.g. a shipment table's Company/Port/Commodity/Quantity columns) - was
rejected: `TableCell` has no FK to `ExtractedEntity` (Phase 3.2 is
frozen), so that join would be weak, string-matched evidence with real
false-positive risk. Documented as a future extension point below.

Every pair of node-eligible entities sharing a chunk is ordered
left-to-right by mention offset (`domain.order_mentions_by_offset`), and
the text between them is sliced (`domain.connector_text`) for pattern
matching - never across a full chunk's text, only the short connecting
phrase, so a "relationship" spanning half a paragraph is correctly
treated as coincidental co-occurrence, not evidence.

### Rule Engine: 7 rules, one per spec example, mirroring `ValidationRuleRegistry`

`RelationshipRuleRegistry` (`app/modules/graph/rules/registry.py`) is
the same in-process, non-versioned registry shape `ValidationRuleRegistry`
established in Phase 3.3 - a new relationship type is a registration
call in `builtin.py`, never a new branch inside an agent. Keyed by the
unordered entity-type pair a rule applies to
(`frozenset({EntityType.COMPANY, EntityType.PORT})`), so lookup is
order-independent.

Exactly 7 rules, one per relationship the spec names as an example:
`CompanyOwnsPortRule` (`owns`), `CompanyOperatesTerminalRule`
(`operates`), `CommodityShippedFromPortRule` (`shipped_from`),
`CommodityShippedToCountryRule` (`shipped_to`),
`ContractReferencesCommodityRule` (`references`),
`CompanyLocatedInCountryRule` and `PortLocatedInCountryRule` (both
`located_in`). Each rule checks the connector text's grammatical
direction *and* the two entities' types together - "Port owns Company"
(a real but nonsensical reversal a document could contain) is declined,
never silently flipped into the sensible direction, since flipping it
would assert something the text never actually said.
`ContractReferencesCommodityRule` is the one exception needing no verb
phrase at all - short proximity between a contract and a commodity is
itself the evidence (`evidence_type = "co_occurrence"`), correspondingly
at the lowest base confidence (0.55) of any rule.
`PortLocatedInCountryRule` recognizes two distinct evidence strengths
under one relationship type: an explicit verb phrase
(`evidence_type = "text_pattern"`, confidence 0.70) and bare comma
adjacency like `"Mundra, India"` (`evidence_type = "adjacent_mention"`,
confidence 0.60) - a common market-report writing style that a verb-only
rule would miss entirely.

### Edge confidence: pattern confidence x entity trust, floored

`domain.combine_edge_confidence(base_confidence, entity_a_confidence,
entity_b_confidence)` scales a rule's base confidence by the average of
the two entities' own `ConfidenceScore.overall_score` (Phase 3.3's
output) - a relationship built on two low-trust entities is honestly
reported as low-trust, never inflated by a strong text match alone. A
combined confidence below `MIN_EDGE_CONFIDENCE = 0.3` is discarded
entirely - never persisted as a weak edge, never silently rounded up.

### Node identity: `canonical_id`, never a raw entity id

A node only exists once `NormalizationResult.canonical_id` has resolved
an entity's identity - unresolved entities stay in the review queue
(Phase 3.3), never enter the graph, keeping "Trusted Entities ->
Relationships" literal. Node-eligible types
(`domain.GRAPH_NODE_ELIGIBLE_TYPES`) are the identity-bearing subset of
`EntityType`: `COMPANY`, `PORT`, `COUNTRY`, `COMMODITY`, `CONTRACT`,
`TERMINAL`, `VESSEL`, `ORGANIZATION`. `CURRENCY`/`PRICE`/`DATE`/
`QUANTITY`/`UNIT`/`INCOTERM`/`HS_CODE` are attributes of a node, never
themselves a node in a business relationship graph.

### Rebuild is idempotent reconciliation, not delete-then-recreate

Trust's persistence pattern (delete every `extraction_run_id`-scoped row,
then re-insert) doesn't fit here: the graph is a **cumulative** structure
spanning the whole corpus, not a per-run snapshot. `PersistGraphResultsAgent`
instead **upserts**: an existing `(source_node_id, target_node_id,
relationship_type)` edge gets new evidence folded in (`evidence_count`
recomputed as `COUNT(DISTINCT chunk_id)`, `confidence` taking the
**max** of old and new - more corroborating evidence should never
*lower* confidence, and a weak duplicate should never dilute a strong
original) rather than duplicated. `GraphEvidence` rows are deduplicated
by `(edge_id, entity_id, chunk_id)` before insert, so re-running a build
on unchanged data is a true no-op - verified directly
(`test_rerunning_is_idempotent_not_additive` in both the unit and
integration suites). `POST /graph/rebuild` is safe to call repeatedly.

### `GraphEvidence.entity_id` is singular; a relationship has two entities

The spec's field list gives `graph_evidence` a single `entity_id`
column, but a relationship connects two. Resolved by writing **two**
evidence rows per detected relationship instance - one for the
source-side entity, one for the target-side - sharing `edge_id`/
`document_id`/`extraction_run_id`/`chunk_id`/`prompt_hash`. This
satisfies the literal schema without adding a column, and doubles as the
natural "which entity mentions support this edge" query
(`GET /graph/edges/{id}/evidence`).

### Merge: tombstone-and-redirect, not delete

Confirmed with the user via `AskUserQuestion`: `POST /graph/merge`
absorbs a duplicate node (e.g. an alias gap the canonical registry
missed) into a survivor by setting `status = merged` and
`merged_into_id`, never deleting the row - consistent with this
codebase's established non-destructive posture (Phase 3.3's review
queue keeps history; trust re-computation never deletes a prior run).
`KnowledgeGraphService.merge_nodes` re-points every edge touching the
absorbed node onto the survivor; an edge that would become a self-loop
after the merge (both endpoints now the same node) is dropped rather
than persisted as something meaningless; a duplicate edge created by the
re-point (the survivor already had the same `(source, target,
relationship_type)`) has its evidence merged into the survivor edge and
is itself deleted. `GET /graph/entity/{canonical_id}` returns a
tombstoned node exactly as stored (`status: "merged"`,
`merged_into_id` visible) rather than silently redirecting - callers see
the merge and can follow it themselves.

### `GraphBuilderService` and `KnowledgeGraphService`: the spec's own class names, with the spec's own responsibilities

The spec names both classes explicitly, and their responsibilities map
directly onto this module's actual split:
- **`GraphBuilderService`** (`builder_service.py`) - create nodes, merge
  aliases, create edges, attach provenance, avoid duplicate nodes/edges,
  maintain evidence counts. Wraps `build_graph_pipeline()`'s
  `SequentialEngine` run for one extraction run
  (`build_for_extraction_run`) and a full-corpus sweep across every
  extraction run with a COMPLETED trust pipeline run (`build_all`).
  Deliberately called *by* the worker task (`run_graph_rebuild`) rather
  than the worker building the `SequentialEngine` pipeline inline the
  way `run_trust_pipeline` does - the spec names this class with this
  exact orchestration responsibility, so it belongs here, not duplicated
  at the call site.
- **`KnowledgeGraphService`** (`query_service.py`) - traversal, merge,
  expansion, filtering, relationship validation. Every read (nodes,
  edges, evidence, entity lookup, relationships, neighbors, subgraph,
  shortest path) plus `merge_nodes`. Never builds the graph itself.
- **`GraphService`** (`service.py`) - not spec-named, added for the same
  reason `TrustPipelineService` exists: the API-facing trigger/read
  lifecycle for `graph_build_runs` (mirrors `POST /extraction-runs/{id}/
  validate` triggering an ARQ job and polling its status).

`build_all`'s failure handling is deliberately partial-progress-preserving:
if extraction run *N* in a full-corpus sweep fails, every run processed
before it has already been validly upserted into the graph (the upsert
model has no notion of "undo run 1 because run 4 failed") -
`GraphBuildPartialFailure` carries the stats accumulated so far, and the
worker records the build as `FAILED` with those real partial stats
rather than reporting a sweep that made progress as having done nothing.
A retry only ever redoes the missing work, since rebuild is idempotent.

### Traversal: hand-rolled recursive CTEs, not a graph library

`networkx` is not a dependency (checked - absent from `pyproject.toml`
and the installed tree), and this repo has an established posture of
deferring extra libraries/engines until a phase genuinely needs them
(`pgvector`/`LangGraph` are both explicitly documented as deferred, not
adopted, in earlier phases). Neighbor expansion, subgraph generation, and
shortest-path all reduce to bounded-depth graph traversal
(`MAX_TRAVERSAL_DEPTH = 6`), which a Postgres `WITH RECURSIVE` CTE
handles natively - `GraphEdgeRepository.reachable_node_ids`/
`shortest_path_node_ids` (`app/modules/graph/repository.py`). Both track
a visited-node `path` array to prevent infinite loops on a real cycle in
the graph (e.g. two companies mutually referencing each other), treating
edges as undirected for reachability purposes.

One real bug this surfaced, caught by the integration test suite against
a real Postgres (a mocked-repository unit test can't exercise real SQL):
`SELECT :param::uuid` - a bind parameter immediately
followed by Postgres's `::` cast operator with no space - is silently
mishandled by SQLAlchemy's `text()` bind-parameter parser on this
asyncpg/SQLAlchemy combination; the parameter is dropped rather than
substituted, producing a raw Postgres syntax error. Fixed by using
`CAST(:param AS uuid)` throughout instead of `:param::uuid` - functionally
identical, unambiguous to the parser. Documented as a comment at both
call sites so a future edit doesn't reintroduce the `::` form.

A second real bug was caught by a *unit* test instead:
`KnowledgeGraphService.shortest_path` originally paired up consecutive
path nodes with `zip(path_node_ids, path_node_ids[1:], strict=True)` -
`strict=True` requires both iterables be the same length, but
`path_node_ids[1:]` is *always* exactly one shorter than
`path_node_ids` (the standard "each node with its successor" pairwise
idiom), so this raised `ValueError` on every single call that found a
real path. `test_shortest_path_returns_nodes_and_hop_edges` (a mocked-
repository unit test - no real database needed to catch this one) failed
immediately; fixed to `strict=False` with a comment explaining why
`strict=True` was wrong here, not just removed silently.

### Ontology/relationship-type reference data: DB tables, not static JSON - a deliberate reversal of Phase 3.3's own precedent

Phase 3.3 chose static in-repo JSON for `CanonicalRegistry` (confirmed
via `AskUserQuestion` at the time). Phase 4 does the opposite for
`ontology_types`/`relationship_types` - real database tables, seeded via
an Alembic data migration (`59226041fb77`), not JSON files - because
*this* spec explicitly names them as tables with real relational
properties (`parent_type` self-reference for a type hierarchy,
`inverse_relationship` self-reference, `symmetric`/`transitive` flags a
future traversal enhancement can query) rather than a flat alias lookup.
`graph_nodes.node_type` and `graph_edges.relationship_type` carry real
foreign keys into these tables (`ON DELETE RESTRICT`) - a node or edge
can never reference an unregistered type, enforced by the schema, not
an application check. Seed data: 8 ontology types (`company` parented
under `organization`, `terminal` parented under `port`, the rest
top-level) and 10 relationship types (the 6 the built-in rules actually
produce, plus 4 inverse-only rows - `owned_by`, `operated_by`,
`referenced_by`, `contains` - that exist for ontology completeness and a
future traversal enhancement, never themselves written to
`graph_edges.relationship_type` by the current rules). Not exposed via
their own API endpoints - internal reference data the builder and
traversal logic consume, not something the spec's literal API list asks
to expose.

### RBAC: new permissions, not reused

Unlike `trust/`, which reuses `extraction:trigger`/`extraction:read`
(no new actor was introduced that phase), Phase 4 adds `graph:read` and
`graph:rebuild` - a genuinely new resource with a genuinely new
capability (rebuilding and correcting a corpus-wide structure, not
triggering one run's pipeline). Granted to `viewer`/`analyst` via the
same data-migration pattern `ec2182df58d8` established
(`a1494375c932`); `admin` already has `"*"` and needs no change.

### Deltas from the original Phase 4 spec, made as engineering calls

Flagged to the user before implementation via `AskUserQuestion`
(relationship-evidence scope, merge semantics), or made and disclosed
during implementation:

1. **Relationship evidence scoped to same-chunk text-pattern matching
   only** - table-row relationship mining declined for this phase; see
   above. Future extension point: add an `entity_id` FK to `TableCell`
   first.
2. **Merge is tombstone-and-redirect, not hard delete** - see above.
3. **`graph_build_runs` added** beyond the spec's literal 5 tables -
   the "run" record `POST /graph/rebuild` needs, mirroring
   `trust_pipeline_runs`.
4. **`graph_nodes` gained `status`/`merged_into_id`** beyond the spec's
   literal field list - required to implement the confirmed
   tombstone-and-redirect merge strategy at all.
5. **`graph_edges` gained `updated_at`** beyond the spec's literal field
   list - unlike Phase 3.3's fact tables, an edge is not append-only;
   rebuilding folds new evidence into the same row in place.
6. **`ontology_types`/`relationship_types` are real DB tables**, a
   deliberate reversal of Phase 3.3's static-JSON precedent for
   canonical reference data - this spec explicitly names them as
   tables with relational properties (hierarchy, inverses) a flat file
   can't express as cleanly.
7. **`graph_evidence.entity_id`'s singular column resolved by writing
   two rows per relationship instance** (source-side, target-side) -
   see above; satisfies the literal schema without adding a column.
8. **New RBAC permissions (`graph:read`/`graph:rebuild`)** rather than
   reusing extraction's, since this is a genuinely new capability - the
   opposite call Phase 3.3 made, for the opposite reason (Phase 3.3
   introduced no new actor; Phase 4 does).

## Verification (all real, not just written)

Every claim above was checked, not assumed:
- `ruff check .` and `mypy app` (strict mode) both pass clean across all
  168 source files.
- `alembic upgrade head` / `downgrade base` / `upgrade head` round-trips
  cleanly against a real Postgres 16 instance; `alembic check` confirms
  zero drift between the ORM models and the migrations, verified again
  after Phase 4's two new migrations (`59226041fb77` - the 6 graph
  tables plus seeded ontology/relationship reference data;
  `a1494375c932` - the `graph:read`/`graph:rebuild` role grants). The
  Phase 3.3 migration adds 5 new native enum types (`trust_pipeline_status`,
  `validation_severity`, `validation_category`, `review_status`,
  `review_priority`); Phase 4's adds 2 more (`graph_node_status`,
  `graph_build_status`) - `graph_build_status` deliberately reuses
  `ExtractionStatus`'s Python values but as its *own* Postgres type name,
  same reasoning as `trust_pipeline_status`, so this migration's
  downgrade can never risk an unrelated table's type.
- 745 tests (`pytest`): 742 pass, 3 skip cleanly
  (`tests/integration/ai/test_groq_live.py` without a `GROQ_API_KEY`).
  95% overall statement coverage on `app/`; every file in
  `app/modules/extraction/trust/` is at 82%+, most at 94-100%; every file
  in `app/modules/graph/` is at 93%+, most at 100% (see Phase 4's own
  bullet below). A handful of FastAPI route return-statement lines in
  `trust/api.py` report as "missed" by `coverage.py` despite being
  exercised by passing, assertion-checked 200-status integration tests -
  a known category of measurement artifact with SQLAlchemy's
  greenlet-based async I/O, not an actual gap; disclosed here rather
  than silently claiming 100%. Split:
  - `tests/unit/extraction/trust/` - no live services. `domain.py`'s pure
    functions (flexible date parsing, numeric parsing, slugification,
    tolerance comparison, weighted-average score math) tested standalone;
    every one of the 11 validation rules tested individually against
    in-memory `ExtractedEntity`/`ExtractedTable`/`TableCell` factories
    (`tests/unit/extraction/trust/rules/_factories.py`); the real seeded
    `reference_data/*.json` files smoke-tested (not just synthetic
    entries) to catch a malformed file or broken loader path immediately;
    each of the 5 trust agents tested against mocked repositories, same
    pattern Phase 3.2 established for `PersistResultsAgent`.
  - `tests/integration/extraction/trust/` - real Postgres.
    `test_worker_pipeline.py` calls `run_trust_pipeline` directly against
    a real completed extraction run (real entities including a
    deliberately-invalid currency code, a real table with a deliberately-
    mismatched stated total) and asserts on the real persisted
    `validation_results`/`confidence_scores`/`normalization_results`/
    `review_queue` rows, including idempotent re-run (no row duplication
    on a second call). `test_api.py` covers the HTTP/RBAC surface
    (trigger/list/get, review-queue CRUD, `viewer` vs `analyst`
    permissions, 404/409 handling). `tests/integration/extraction/
    test_api.py` (Phase 3.2's own file) gained two new tests for the
    extraction-fingerprint dedup path: an identical fingerprint returns
    the existing `COMPLETED` run without creating a new one or enqueuing a
    job; a different document hash creates a genuinely new run.
  - **Live Docker verification, not just pytest**: rebuilt the `api`/
    `worker` images, brought the stack up, ran `alembic upgrade head`
    inside the container, registered a user, promoted to `analyst`,
    seeded a real completed extraction run (3 entities including one
    invalid currency code, one table with a mismatched total) via a
    script run inside the live `api` container, then triggered
    `POST /extraction-runs/{id}/validate` through the real HTTP API - the
    real `worker` container picked the job up off real Redis and
    completed it in 304ms. Confirmed live: `entities_validated: 3`,
    `entities_flagged_for_review: 1`, the invalid-currency entity's
    review-queue reason correctly merged three distinct triggers
    ("overall confidence 0.39 is very low; unresolved canonical identity;
    validation failed (currency.invalid_code): ...") into one row at
    `priority: high`, the table-total mismatch was caught with
    `entity_id: null` exactly as designed, the valid `USD` entity resolved
    to `canonical_id: currency:USD` via real alias lookup, and
    `PATCH /review-queue/{id}` correctly resolved the item with a
    `reviewed_at` timestamp. Scratch data cleaned up via cascade delete
    afterward.
  - Dead code caught and removed before shipping, not left in "for
    completeness": `ConfidenceScoreRepository.average_overall_for_run`,
    `NormalizationResultRepository.get_for_entity`/`list_for_run`, and
    `ValidationResultRepository.list_for_entity` were written speculatively
    during initial repository design, never actually called by any service
    or agent, and were deleted once `grep` confirmed zero call sites -
    `BaseRepository.get_by_id` already covers the entity-lookup case for
    the two tables that use `entity_id` as their primary key.
- **Phase 4: 136 new tests, 96% coverage on `app/modules/graph/`.**
  - `tests/unit/graph/` - no live database. `domain.py`'s pure functions
    (mention ordering, connector-text slicing, confidence combination)
    tested standalone; all 7 relationship rules tested individually
    against in-memory `ExtractedEntity`/`EntityMention` factories built
    from real `str.index()` offsets (`tests/unit/graph/rules/_factories.py`
    - deliberately not hand-counted character offsets, after an early
    hand-counted test offset was itself wrong by one character and
    caught by its own assertion failure); each of the 3 graph agents
    tested against mocked repositories (`NodeResolutionAgent`,
    `RelationshipExtractionAgent`) or lightweight stateful in-memory fake
    repositories (`PersistGraphResultsAgent` - its upsert/dedup logic has
    enough create-then-lookup statefulness that a fake repository
    catches real logic bugs a flat `AsyncMock` return value would miss);
    `GraphBuilderService`/`GraphService`/`KnowledgeGraphService` tested
    against mocked or fake repositories, including `merge_nodes`'s
    edge-repoint/self-loop-drop/duplicate-edge-merge branches.
  - `tests/integration/graph/` - real Postgres. `test_worker_pipeline.py`
    calls `run_graph_rebuild` directly against a real trusted extraction
    (a real chunk of text - `"Adani Ports owns Mundra Port in
    Gujarat."` - with real entities/mentions/normalization/confidence
    rows) and asserts on the real persisted `graph_nodes`/`graph_edges`/
    `graph_evidence` rows, including idempotent re-run (identical
    `evidence_count`, no duplicate evidence rows) and the
    trust-not-completed failure path. `test_api.py` covers the full
    HTTP/RBAC surface (rebuild trigger, build-run polling, nodes, edges,
    evidence, entity/relationships lookup, neighbors, subgraph, shortest
    path including the unreachable case, merge). `test_repository.py`
    covers the ontology/relationship-type reference-data reads (seeded
    by migration, never exposed via API) and a few real-database-only
    edge cases (a genuine multi-hop merge chain, `count_nodes`/
    `count_edges` filter combinations) mocking can't meaningfully exercise.
  - **Two real bugs caught by this test suite before shipping, both
    described in full above**: a bind-parameter/`::`-cast interaction in
    the recursive-CTE SQL that made every `subgraph`/`shortest_path` call
    fail outright (caught by the integration suite against real
    Postgres), and a `zip(..., strict=True)` misuse in `shortest_path`
    that made every successful path lookup raise `ValueError` (caught by
    a mocked-repository unit test, no database needed). Both fixed with
    a comment explaining *why* the fix is correct, not just what changed.

## Folder structure (current)

```
CMIP/
|-- backend/
|   |-- app/
|   |   |-- core/               # config, logging, exceptions, db session, security, rate_limit, middleware, metrics
|   |   |-- common/             # ApiResponse/PaginatedResponse, BaseRepository, BaseService
|   |   |-- ai/                 # AI infrastructure (Phase 3.1) - not wired into modules/ yet
|   |   |   |-- engine/         # AgentEngine (ABC), SequentialEngine, RetryPolicy/CancellationToken/AgentContext/...
|   |   |   |-- agents/         # Agent Protocol only - no concrete agent yet
|   |   |   |-- providers/      # LLMProvider (ABC), ProviderCapabilities, ProviderRegistry, groq/claude/openai/ollama, factory
|   |   |   |-- client/         # LLMClient - centralized retry/logging/token-accounting/provider-selection
|   |   |   |-- structured/     # StructuredOutputService - validate + retry-on-invalid
|   |   |   |-- prompts/        # PromptPackage (data shape only; Prompt Registry is later)
|   |   |   |-- observability/  # call-metadata logging + Prometheus recording, secret redaction
|   |   |   `-- exceptions.py   # AIError hierarchy, independent of app.core.exceptions
|   |   |-- modules/
|   |   |   |-- auth/           # models, domain, schemas, repository, service, dependencies, api, admin_api
|   |   |   |-- audit/          # models, schemas, repository, service, api
|   |   |   |-- documents/      # models, domain, schemas, repository, service, api, queue
|   |   |   |   |-- storage/    # base (ABC), local, s3, factory
|   |   |   |   |-- ocr/        # base (ABC), tesseract_provider, paddle_provider
|   |   |   |   |-- extraction/ # pdf_extractor, table_extractor, image_extractor, layout, types
|   |   |   |   |-- chunking/   # chunker
|   |   |   |   `-- security/   # signing (local signed URLs), virus_scan
|   |   |   |-- extraction/     # (Phase 3.2) models, domain, geometry, repository, service, schemas, api, pipeline, queue
|   |   |   |   |-- agents/     # schemas + DocumentUnderstanding/Layout/EntityExtraction/TableExtraction/PersistResults
|   |   |   |   |-- prompts/    # document_understanding, layout_understanding, entity_extraction, table_extraction
|   |   |   |   `-- trust/      # (Phase 3.3) models, domain, repository, service, schemas, api, pipeline
|   |   |   |       |-- agents/         # schemas + Validation/Normalization/Confidence/ReviewQueue/PersistTrustResults
|   |   |   |       |-- rules/          # types, registry, builtin + one module per rule category
|   |   |   |       |-- normalization/  # CanonicalRegistry, loader (lru_cache-wrapped bundle)
|   |   |   |       `-- reference_data/ # countries/currencies/units/incoterms/hs_code_prefixes/commodities/ports.json
|   |   |   `-- graph/          # (Phase 4) models, domain, repository, builder_service, query_service, service, schemas, api, pipeline, queue, exceptions
|   |   |       |-- agents/     # schemas + NodeResolution/RelationshipExtraction/PersistGraphResults
|   |   |       `-- rules/      # types, registry, builtin + one module per relationship category
|   |   |-- worker/             # context (object graph), settings (ARQ WorkerSettings), tasks (process_document, run_extraction, run_trust_pipeline, run_graph_rebuild)
|   |   `-- main.py             # FastAPI app factory
|   |-- alembic/                # async env.py, versioned migrations
|   |-- tests/
|   |   |-- unit/                # mirrors app/, no live DB/services (but real Tesseract/PyMuPDF/moto-server/mocked-SDK where it matters)
|   |   `-- integration/         # real Postgres/Redis for documents/auth/audit/extraction/trust/graph; tests/integration/ai/ needs neither, skips on missing API key
|   |-- pyproject.toml
|   `-- Dockerfile               # includes tesseract-ocr apt package
|-- docker-compose.yml           # postgres, redis, api, worker (shared documents_data volume)
|-- .github/workflows/
|   `-- backend-ci.yml
`-- docs/
    |-- ARCHITECTURE.md          # this file
    `-- DATABASE.md
```

Modules not yet built (`pricing`, `freight`, `premiums`, `commentary`,
`analytics`, `search`, `chat`, `dashboard`) will land as their phase is
implemented. `app/modules/extraction/` is document-scoped business logic
(the five agents, prompts, persistence) built on top of `app/ai/`'s
generic engine/provider infrastructure - the same layering split as
`app/modules/documents/` sitting on top of `app/core/`. `app/modules/graph/`
sits one layer higher still: it consumes `extraction`'s and `trust`'s
already-persisted output (via their repositories) but is not nested
inside either, since it aggregates across every document/run in the
corpus rather than being scoped to one.

## Roadmap

| Phase | Scope |
|---|---|
| **1 - done** | Foundation: auth, RBAC, audit, rate limiting, observability bedrock |
| **2 - done** | Document ingestion: `documents`/`document_versions`/`processing_jobs`/`document_chunks`, upload+storage (local/S3), ARQ worker with retry/backoff/dead-letter, OCR (Tesseract) + PDF/table/layout extraction, chunking |
| **3.1 - done** | AI Engine & LLM Infrastructure: `AgentEngine`/`SequentialEngine`, `LLMProvider` (Groq/Claude/OpenAI/Ollama), `LLMClient`, `StructuredOutputService`, `PromptPackage`, `ProviderRegistry`, observability |
| **3.2 - done** | Semantic Document Intelligence: `PromptRegistry` + `DocumentUnderstandingAgent`/`LayoutAgent`/`EntityExtractionAgent`/`TableExtractionAgent`/`PersistResultsAgent` + `extraction_runs`/`extracted_entities`/`entity_mentions`/`extracted_tables`/`table_cells`, real PyMuPDF/pdfplumber coordinate grounding, own trigger/status API |
| **3.3 - done** | Trust, Validation & Canonicalization: `ValidationAgent`/`NormalizationAgent`/`ConfidenceAgent`/`ReviewQueueAgent` (no LLM call - deterministic rules/lookups/scoring), configurable `ValidationRuleRegistry` (11 built-in rules), static `CanonicalRegistry` reference data, `trust_pipeline_runs`/`validation_results`/`confidence_scores`/`normalization_results`/`review_queue`, extraction fingerprint dedup, own trigger/status API |
| **4 - done** | Knowledge Graph & Semantic Intelligence: `NodeResolutionAgent`/`RelationshipExtractionAgent`/`PersistGraphResultsAgent` (no LLM call - deterministic text-pattern matching over same-chunk co-occurrence), configurable `RelationshipRuleRegistry` (7 built-in rules), `graph_nodes`/`graph_edges`/`graph_evidence`/`ontology_types`/`relationship_types`/`graph_build_runs`, hand-rolled recursive-CTE traversal (neighbors/subgraph/shortest path), tombstone-and-redirect node merge, own trigger/status API |
| **5** | Commentary, Executive Briefs, Embeddings/RAG (pgvector), AI Chat, `LangGraphEngine` as a second `AgentEngine` backend if a pipeline needs graph/DAG execution |
| **6** | Analytics & dashboard APIs |
| **7** | Frontend |
| **8** | Security/observability hardening, Nginx |
| **9** | Full CI/CD, deployment guide |
| **10** | Documentation & final QA |

Each phase gets its own review checkpoint before the next one starts.
