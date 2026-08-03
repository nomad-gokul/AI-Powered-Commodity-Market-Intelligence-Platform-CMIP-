# AI Commodity Market Intelligence Platform (CMIP)

Enterprise platform that converts commodity market reports (Platts, Argus,
Energy Intelligence, internal reports) into structured, AI-generated
intelligence: benchmark prices, freight rates, market events, risks, and
commentary.

**Status: Phase 1 (Foundation), Phase 2 (Document Ingestion), Phase 3.1
(AI Engine & LLM Infrastructure), Phase 3.2 (Semantic Document
Intelligence), Phase 3.3 (Trust, Validation & Canonicalization), and
Phase 4 (Knowledge Graph & Semantic Intelligence) complete.** Auth, RBAC,
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
all implemented and verified. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full roadmap.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Alembic,
Redis, structlog, JWT (python-jose), bcrypt (passlib) - Phase 1. ARQ
(background jobs), PyMuPDF + pdfplumber (extraction), Tesseract OCR
(pytesseract), aioboto3/boto3 (S3), tiktoken (chunking), Prometheus client -
Phase 2. Groq/Anthropic/OpenAI SDKs + httpx (Ollama), tenacity - Phase 3.1.
Phase 3.2 adds no new dependencies - it's built entirely on Phase 3.1's
engine/provider infrastructure plus the PyMuPDF/pdfplumber already in
Phase 2. Phase 3.3 adds no new dependencies either - its rule engine and
canonical registry are pure Python/JSON, no LLM SDK involved. Phase 4
also adds no new dependencies - its relationship rule engine is pure
Python/regex, and graph traversal (neighbors, subgraph, shortest path)
is hand-rolled Postgres `WITH RECURSIVE` SQL rather than a graph
library (`networkx` was considered and deliberately not adopted - see
docs/ARCHITECTURE.md). Later phases add pgvector, LangGraph, and the
Next.js frontend as each is implemented.

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
```

Admin-only routes (`/api/v1/roles`, `/api/v1/users`, `/api/v1/audit-logs`)
need a user with the `admin` role - assign it directly in the database for
now (`INSERT INTO user_roles ...`); an admin-assignment API exists at
`POST /api/v1/users/{id}/roles` but requires an existing admin to call it.
Deleting, reprocessing, triggering extraction, triggering the trust
pipeline, resolving review-queue items, rebuilding the graph, and merging
graph nodes all need the `analyst` or `admin` role; `viewer` can upload,
read, and read extraction/trust/graph results, but not trigger anything
or delete/reprocess/resolve/rebuild/merge.

## Running tests

```bash
cd backend
pip install -e ".[dev]"
ruff check .              # lint
mypy app                  # type check (strict)
alembic upgrade head      # apply migrations to a real Postgres first
pytest --cov=app --cov-report=term-missing
```

`tests/unit/` needs no database (it does call the real, installed
Tesseract binary and a real local moto S3 server - see
`docs/ARCHITECTURE.md`'s OCR/storage testing notes; `app/ai/`'s provider
tests use mocked SDK clients only, no live vendor calls). `tests/integration/`
needs a real Postgres + Redis reachable at the URLs in `backend/.env`
(each test runs in a rolled-back transaction, so it's safe to point at a
real dev database - see `tests/integration/conftest.py`) - **except**
`tests/integration/ai/test_groq_live.py`, which needs neither: it calls
the real Groq API directly and skips cleanly if `GROQ_API_KEY` isn't set.
Set `OCR_TESSERACT_CMD` in `backend/.env` if `tesseract` isn't on your
`PATH` (Windows almost always needs this - see `.env.example`).

To exercise the live Groq test, add a real key to `backend/.env`:

```bash
GROQ_API_KEY=gsk_...
```

## Local development without Docker

```bash
cd backend
pip install -e ".[dev]"
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
