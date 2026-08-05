# AI Commodity Market Intelligence Platform (CMIP)

Enterprise platform that converts commodity market reports (Platts, Argus,
Energy Intelligence, internal reports) into structured, AI-generated
intelligence: benchmark prices, freight rates, market events, risks, and
commentary.

**Status: Phase 1 (Foundation), Phase 2 (Document Ingestion), Phase 3.1
(AI Engine & LLM Infrastructure), Phase 3.2 (Semantic Document
Intelligence), Phase 3.3 (Trust, Validation & Canonicalization),
Phase 4 (Knowledge Graph & Semantic Intelligence), Pre-Phase 5 (AI
Service Extraction), and Phase 5 (Knowledge Retrieval Platform)
complete.** Auth, RBAC,
audit logging, document upload/storage, background OCR + text/table
extraction + chunking, a provider-agnostic AI engine (`AgentEngine` +
`LLMProvider`, real Groq/Claude/OpenAI/Ollama implementations), a
five-agent extraction pipeline that turns a document's chunks into
normalized entities and structured tables (grounded in real
PyMuPDF/pdfplumber coordinates, never LLM-guessed), a second,
deterministic pipeline - no LLM call anywhere - that validates those
entities against a configurable rule engine, resolves them to canonical
identities/values, computes an 8-dimension confidence score per entity,
and queues low-trust entities for human review, and a third, also
deterministic pipeline that turns those trusted, canonicalized entities
into a persistent, queryable knowledge graph of business relationships
(ownership, operation, shipment, location, contractual reference) with
full evidence provenance and hand-rolled recursive-CTE traversal, are
all implemented and verified. A purely architectural refactor (zero
functional change) split the AI infrastructure out of
`backend/app/ai` into two new sibling packages - `ai-service/` and
`shared/` - so a future move to a real standalone AI deployment is a
transport swap, not a rewrite. Most recently, a hybrid retrieval platform
(`HybridRetriever`) combines PostgreSQL full-text search (BM25), pgvector
similarity search, and knowledge-graph expansion into one ranked, fully
cited result set - `EmbeddingProvider`/`EmbeddingService`,
`QueryAnalyzer`, `RerankerService`, `CitationEngine`,
`ContextBuilder`/`ContextService` - no LLM call anywhere in this phase
either; it is the retrieval foundation later phases (Commentary,
Forecasting, AI Copilot) will query through. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full roadmap.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Alembic,
Redis, structlog, JWT (python-jose), bcrypt (passlib) - Phase 1. ARQ
(background jobs), PyMuPDF + pdfplumber (extraction), Tesseract OCR
(pytesseract), aioboto3/boto3 (S3), tiktoken (chunking), Prometheus client -
Phase 2. Groq/Anthropic/OpenAI SDKs + httpx (Ollama) - Phase 3.1.
Phase 3.2 adds no new dependencies - it's built entirely on Phase 3.1's
engine/provider infrastructure plus the PyMuPDF/pdfplumber already in
Phase 2. Phase 3.3 adds no new dependencies either - its rule engine and
canonical registry are pure Python/JSON, no LLM SDK involved. Phase 4
also adds no new dependencies - its relationship rule engine is pure
Python/regex, and graph traversal (neighbors, subgraph, shortest path)
is hand-rolled Postgres `WITH RECURSIVE` SQL rather than a graph
library (`networkx` was considered and deliberately not adopted - see
docs/ARCHITECTURE.md). Pre-Phase 5 adds no new dependencies either -
it's a pure code-relocation: the AI SDKs above moved from `backend/`'s
own `pyproject.toml` into a new sibling package, `ai-service/`, and
`tenacity` (a declared-but-never-imported Phase 3.1 dependency, caught
incidentally during the move) was dropped rather than carried forward,
since `LLMClient`'s retry policy is hand-rolled and never used it.
Phase 5 adds PostgreSQL's pgvector extension (`pgvector/pgvector:pg16` in
Docker) plus two new Python dependencies: `pgvector` (backend-only, the
SQLAlchemy `Vector` column type) and `python-dateutil` (backend-only,
`QueryAnalyzer`'s time-range parsing) - embeddings themselves need no new
SDK, reusing the `openai` package and `httpx` already installed for LLM
calls since Phase 3.1. The Next.js frontend and LangGraph remain for a
later phase.

## Quickstart

1. Copy the env template:

   ```bash
   cp .env.example .env
   # generate a real secret: python -c "import secrets; print(secrets.token_urlsafe(64))"
   # and set it as JWT_SECRET_KEY
   ```

2. Start Postgres, Redis, the API, and the ingestion worker:

   ```bash
   docker compose up --build
   ```

3. Run migrations (first time, and after any model change):

   ```bash
   docker compose exec api alembic upgrade head
   ```

4. API docs: http://localhost:8010/docs (note: port 8010, not 8000 - see
   `docker-compose.yml` for why)

## Try it

```bash
# Register (default role: viewer)
curl -X POST http://localhost:8010/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","full_name":"Your Name","password":"a-strong-password"}'

# Log in
curl -X POST http://localhost:8010/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"a-strong-password"}'

# Use the access_token from the response
curl http://localhost:8010/api/v1/users/me \
  -H "Authorization: Bearer <access_token>"

# Upload a document (viewer role can upload+read by default)
curl -X POST http://localhost:8010/api/v1/documents/upload \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@report.pdf;type=application/pdf"

# Check processing status (the "worker" container picks the job up from
# Redis and runs OCR/extraction/chunking in the background)
curl http://localhost:8010/api/v1/processing-jobs/<job_id> \
  -H "Authorization: Bearer <access_token>"

# Once ingestion completes, trigger semantic extraction (needs analyst/admin -
# a separate lifecycle from ingestion, see docs/ARCHITECTURE.md; requires a
# real LLM_PROVIDER/API key configured, e.g. GROQ_API_KEY in backend/.env)
curl -X POST http://localhost:8010/api/v1/documents/<document_id>/extract \
  -H "Authorization: Bearer <access_token>"

# Check extraction status, then read results
curl http://localhost:8010/api/v1/extraction-runs/<extraction_run_id> \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/documents/<document_id>/entities \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/documents/<document_id>/tables \
  -H "Authorization: Bearer <access_token>"

# Once extraction is COMPLETED, trigger the trust pipeline (needs analyst/admin -
# its own lifecycle from extraction, see docs/ARCHITECTURE.md; deterministic,
# no LLM/API key needed - validation, normalization, and confidence scoring
# are all rule-based/lookup-based)
curl -X POST http://localhost:8010/api/v1/extraction-runs/<extraction_run_id>/validate \
  -H "Authorization: Bearer <access_token>"

# Check trust pipeline status, then read results
curl http://localhost:8010/api/v1/trust-runs/<trust_pipeline_run_id> \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/extraction-runs/<extraction_run_id>/validation-results \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/extracted-entities/<entity_id>/confidence \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/extracted-entities/<entity_id>/normalization \
  -H "Authorization: Bearer <access_token>"

# Review queue: low-confidence/failed-validation/unresolved entities land here
curl http://localhost:8010/api/v1/review-queue \
  -H "Authorization: Bearer <access_token>"
curl -X PATCH http://localhost:8010/api/v1/review-queue/<review_item_id> \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"status":"resolved","resolution":"confirmed correct"}'

# Build the knowledge graph from every trusted extraction run (needs analyst/admin -
# its own lifecycle again; deterministic, no LLM/API key needed - relationship
# extraction is same-chunk text-pattern matching, never inference).
# Omit extraction_run_id for a full-corpus rebuild, or scope it to one run.
curl -X POST http://localhost:8010/api/v1/graph/rebuild \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{}'

# Check the rebuild job, then explore the graph
curl http://localhost:8010/api/v1/graph/build-runs/<graph_build_run_id> \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/graph/nodes \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/graph/entity/company:adani_ports_sez \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/graph/relationships/company:adani_ports_sez \
  -H "Authorization: Bearer <access_token>"
curl "http://localhost:8010/api/v1/graph/nodes/<node_id>/subgraph?depth=2" \
  -H "Authorization: Bearer <access_token>"
curl "http://localhost:8010/api/v1/graph/path?source_canonical_id=company:adani_ports_sez&target_canonical_id=country:india" \
  -H "Authorization: Bearer <access_token>"
curl http://localhost:8010/api/v1/graph/edges/<edge_id>/evidence \
  -H "Authorization: Bearer <access_token>"

# Merge two nodes that should have resolved to the same canonical entity
# (e.g. an alias gap) - tombstones the source, never deletes it
curl -X POST http://localhost:8010/api/v1/graph/merge \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"source_node_id":"<duplicate_node_id>","target_node_id":"<survivor_node_id>"}'

# Graph-only retrieval - no embedding provider needed, works out of the box.
# Auto-detects seed entities from the query text (or pass seed_canonical_ids explicitly).
curl -X POST http://localhost:8010/api/v1/retrieve/graph \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"query":"What does Adani Ports SEZ own?"}'

# Full hybrid retrieval (BM25 + pgvector + graph expansion) and structured
# context assembly need a real embedding provider configured
# (EMBEDDING_PROVIDER + OPENAI_API_KEY/OLLAMA_BASE_URL in backend/.env) -
# without one, both return 503 rather than a partial/misleading result.
curl -X POST http://localhost:8010/api/v1/retrieve \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"query":"who owns Mundra Port?","top_k":10}'
curl -X POST http://localhost:8010/api/v1/retrieve/context \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"query":"who owns Mundra Port?"}'

# Read back a persisted retrieval run and its ranked, cited results
curl http://localhost:8010/api/v1/retrieval-runs/<retrieval_run_id> \
  -H "Authorization: Bearer <access_token>"
```

Admin-only routes (`/api/v1/roles`, `/api/v1/users`, `/api/v1/audit-logs`)
need a user with the `admin` role - assign it directly in the database for
now (`INSERT INTO user_roles ...`); an admin-assignment API exists at
`POST /api/v1/users/{id}/roles` but requires an existing admin to call it.
Deleting, reprocessing, triggering extraction, triggering the trust
pipeline, resolving review-queue items, rebuilding the graph, and merging
graph nodes all need the `analyst` or `admin` role; `viewer` can upload,
read, and read extraction/trust/graph results, but not trigger anything
or delete/reprocess/resolve/rebuild/merge. Retrieval (`/retrieve`,
`/retrieve/context`, `/retrieve/graph`, `/retrieval-runs/{id}`) needs only
`retrieval:read`, granted identically to `viewer` and `analyst` - it is
read-only from the caller's perspective even though it performs real
computation and persists a `RetrievalRun` as an audit side effect.

## Running tests

Since Pre-Phase 5, the repo has three local packages (`shared/`,
`ai-service/`, `backend/`) installed editable into one venv; quality
gates run once per package:

```bash
# from the repo root, once:
pip install -e ./shared -e ./ai-service -e "./backend[dev]"

ruff check shared ai-service backend      # lint - all three
mypy --config-file shared/pyproject.toml shared/shared
mypy --config-file ai-service/pyproject.toml ai-service/ai_service
mypy --config-file backend/pyproject.toml backend/app       # each package's own strict config

cd backend && alembic upgrade head        # apply migrations to a real Postgres first

# pytest, once per package:
(cd shared && pytest --cov=shared --cov-report=term-missing)
(cd ai-service && pytest --cov=ai_service --cov-report=term-missing)
(cd backend && pytest --cov=app --cov-report=term-missing)
```

`shared/tests/` and `ai-service/tests/unit/` need no live services
(`ai-service`'s provider tests use mocked SDK clients only, no live
vendor calls) - **except** `ai-service/tests/integration/test_groq_live.py`,
which calls the real Groq API directly and skips cleanly if
`GROQ_API_KEY` isn't set. `backend/tests/unit/` needs no database either
(it does call the real, installed Tesseract binary and a real local moto
S3 server - see `docs/ARCHITECTURE.md`'s OCR/storage testing notes).
`backend/tests/integration/` needs a real Postgres + Redis reachable at
the URLs in `backend/.env` (each test runs in a rolled-back transaction,
so it's safe to point at a real dev database - see
`tests/integration/conftest.py`) - and, since Phase 5, that Postgres must
be a `pgvector/pgvector:pg16` image (or any Postgres with the `vector`
extension installable), not plain `postgres:16-alpine`; `docker-compose.yml`
already uses the pgvector image. Set `OCR_TESSERACT_CMD` in
`backend/.env` if `tesseract` isn't on your `PATH` (Windows almost always
needs this - see `.env.example`).

To exercise the live Groq test, add a real key to `backend/.env` (read
independently by both `backend`'s `Settings` and `ai-service`'s own
`AISettings` - see docs/ARCHITECTURE.md):

```bash
GROQ_API_KEY=gsk_...
```

To exercise `POST /retrieve`/`/retrieve/context` (hybrid retrieval) rather
than just `/retrieve/graph`, add a real embedding provider - `EMBEDDING_PROVIDER`
defaults to `openai` (needs `OPENAI_API_KEY`); `EMBEDDING_PROVIDER=ollama`
needs no key, just a reachable `OLLAMA_BASE_URL`. Without either, those
two routes return a clean `503 service_unavailable` rather than a
partial/misleading result - see docs/ARCHITECTURE.md's Phase 5 section.

```bash
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

## Local development without Docker

```bash
pip install -e ./shared -e ./ai-service -e "./backend[dev]"
cd backend
uvicorn app.main:app --reload
```

To also run the ingestion worker locally:

```bash
cd backend
arq app.worker.settings.WorkerSettings
```

You'll still need Postgres 16, Redis, and a local Tesseract OCR
installation reachable per `backend/.env`.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - layering, design
  decisions and their tradeoffs, what's implemented, the roadmap
- [docs/DATABASE.md](docs/DATABASE.md) - schema reference
