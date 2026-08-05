# Database Schema (Phase 1 + Phase 2 + Phase 3.2 + Phase 3.3 + Phase 4 + Phase 5)

PostgreSQL 16 with the pgvector extension (since Phase 5). Migrations:
`backend/alembic/versions/`. This document covers the twenty-eight tables
that exist today; it grows with each phase. (Phase 3.1 added no tables -
pure AI infrastructure, see docs/ARCHITECTURE.md.)

## Entity-relationship overview

```
users ──< user_roles >── roles
  │
  ├──< refresh_tokens  (self-referencing via replaced_by_token_id, for rotation chains)
  │
  ├──< audit_logs  (user_id is nullable + ON DELETE SET NULL: an audit
  │                  row must outlive the user it recorded)
  │
  ├──< review_queue  (assigned_to -> users, nullable + ON DELETE SET NULL)
  │
  └──< documents  (uploaded_by is nullable + ON DELETE SET NULL, same reasoning)
        │
        ├──< document_versions
        ├──< processing_jobs
        ├──< document_chunks
        └──< extraction_runs  (one per POST /documents/{id}/extract call)
              │
              ├──< extracted_entities  (source_chunk -> document_chunks, nullable + ON DELETE SET NULL)
              │     ├──< entity_mentions
              │     ├──< validation_results  (entity_id nullable - some findings are cross-entity/cross-table)
              │     ├──1:1 confidence_scores  (entity_id is the PK)
              │     └──1:1 normalization_results  (entity_id is the PK)
              │
              ├──< extracted_tables
              │     └──< table_cells
              │
              ├──< trust_pipeline_runs  (one per POST /extraction-runs/{id}/validate call)
              │
              ├──< review_queue  (entity_id -> extracted_entities)
              │
              └──< graph_build_runs  (extraction_run_id nullable - null means a
                    full-corpus rebuild, not scoped to this run)

ontology_types ──self-ref── (parent_type)          relationship_types ──self-ref── (inverse_relationship)
      ▲                                                    ▲
      │ node_type (ON DELETE RESTRICT)                     │ relationship_type (ON DELETE RESTRICT)
      │                                                     │
graph_nodes ──self-ref── (merged_into_id, tombstone chain)  │
  │    ▲                                                    │
  │    └──────────────< graph_edges >──────────────────────┘
  │         (source_node_id, target_node_id, both -> graph_nodes)
  │                        │
  │                        └──< graph_evidence  (edge_id -> graph_edges;
  │                              also entity_id -> extracted_entities,
  │                              document_id -> documents,
  │                              extraction_run_id -> extraction_runs,
  │                              chunk_id -> document_chunks, nullable)
  │
  └── one row per canonical_id - aggregates entities across every
      extraction_run/document in the corpus, not scoped to one

users ──< retrieval_runs  (requested_by_user_id, nullable + ON DELETE SET NULL)
              │
              └──< retrieval_results  (retrieval_run_id -> retrieval_runs)

embeddings  (polymorphic - source_type + source_id, no FK: two of its five
             source types - canonical_entity, ontology_definition - have
             no database row to reference at all)
```

## `users`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | varchar(320) | unique |
| `hashed_password` | varchar(255) | bcrypt |
| `full_name` | varchar(256) | |
| `is_active` | boolean | deactivated accounts fail login and token refresh |
| `created_at`, `updated_at` | timestamptz | see "Timestamp defaults" below |

## `roles`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | varchar(64) | unique, e.g. `admin`, `analyst`, `viewer` |
| `description` | varchar(512) | nullable |
| `permissions` | text[] | permission strings; `"*"` = full access, `"resource:*"` = all actions on a resource. See ARCHITECTURE.md's RBAC section for why this is an array, not a relational table. |

Seeded rows (`8329376ff7a6_seed_default_roles_admin_analyst_viewer.py`,
extended by `5cf29ad980c9_grant_documents_permissions_to_viewer_.py`,
`ec2182df58d8_grant_extraction_permissions_to_viewer_.py`, and
`a1494375c932_grant_graph_permissions_to_viewer_and_.py`):

| name | permissions |
|---|---|
| `admin` | `["*"]` |
| `analyst` | `["audit_logs:read", "documents:upload", "documents:read", "documents:reprocess", "documents:delete", "extraction:trigger", "extraction:read", "graph:rebuild", "graph:read"]` |
| `viewer` | `["documents:upload", "documents:read", "extraction:read", "graph:read"]` (default role for self-registered accounts) |

Phase 3.3 (trust pipeline trigger, review-queue mutation) adds no new
permission strings - `extraction:trigger`/`extraction:read` are reused
as-is, since no new actor was introduced this phase (see ARCHITECTURE.md).
Phase 4 makes the opposite call: `graph:read`/`graph:rebuild` are new
permission strings, since rebuilding/correcting a corpus-wide graph is a
genuinely new capability, not a variant of triggering one extraction
run's pipeline.

## `user_roles`

Plain many-to-many join table: `(user_id, role_id)` composite PK, both
`ON DELETE CASCADE`.

## `refresh_tokens`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK -> users, `ON DELETE CASCADE` | |
| `token_hash` | varchar(64), unique | SHA-256 hex digest of the opaque token; the raw token is never stored |
| `expires_at` | timestamptz | |
| `revoked_at` | timestamptz, nullable | set on logout, rotation, or reuse-detection mass-revoke |
| `replaced_by_token_id` | UUID FK -> refresh_tokens, nullable, `ON DELETE SET NULL` | points to the token this one was rotated into, forming an auditable rotation chain |

## `audit_logs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK -> users, nullable, `ON DELETE SET NULL` | nullable so the row survives user deletion |
| `action` | varchar(128) | e.g. `user.login`, `auth.refresh_token_reuse_detected` |
| `resource_type` | varchar(64) | e.g. `user`, `refresh_token` |
| `resource_id` | UUID, nullable | |
| `metadata` | jsonb | free-form context (Python attribute is `metadata_` - `metadata` is reserved on SQLAlchemy declarative models) |
| `ip_address` | varchar(64), nullable | |
| `created_at` | timestamptz | **no `updated_at`, no update path in the repository** - audit rows are immutable by construction |

## `documents`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `uploaded_by` | UUID FK -> users, nullable, `ON DELETE SET NULL` | |
| `filename` | varchar(255) | server-generated storage-safe name (`{uuid}{ext}`), never derived from client input |
| `original_filename` | varchar(512) | untrusted, sanitized for display only - never used to build a path |
| `extension` | varchar(16) | normalized, lowercase, includes the dot |
| `mime_type` | varchar(128) | |
| `file_size` | bigint | actual bytes written to storage, not a client-declared Content-Length |
| `sha256_hash` | varchar(64), indexed | used for duplicate-upload detection |
| `storage_provider` | enum: `local`, `s3` | |
| `storage_key` | varchar(1024) | |
| `upload_status` | enum: `pending`, `uploaded`, `failed` | |
| `processing_status` | enum: `uploaded`, `queued`, `processing`, `ocr`, `extracting`, `chunking`, `completed`, `failed`, `cancelled` | the document's current pipeline stage - see `processing_jobs` for the distinct job-execution lifecycle |
| `processing_progress` | smallint | denormalized cache of the active job's progress (0-100), avoids a join for `GET /documents/{id}` |
| `language` | varchar(16), nullable | detected via `langdetect`, `null` until the document is processed |
| `page_count` | integer, nullable | |
| `metadata_json` | jsonb | title/author/creation_date/word_count/table_count |
| `deleted_at` | timestamptz, nullable | soft delete - excluded from list/get by default; storage bytes are **not** purged (see Known Limitations in the Phase 2 completion report) |
| `created_at`, `updated_at` | timestamptz | |

## `document_versions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK -> documents, `ON DELETE CASCADE` | |
| `version_number` | integer | unique per `document_id` |
| `uploaded_by` | UUID FK -> users, nullable, `ON DELETE SET NULL` | |
| `storage_key`, `sha256_hash`, `file_size` | | added beyond the originally specified minimal column set - a version row with no pointer to its own bytes would be unreadable |
| `uploaded_at` | timestamptz | |

A version 1 row is created automatically on every upload. No "upload a new
version" endpoint exists yet (not in Phase 2's required API surface), so
in practice every document has exactly one version today; the table is
schema-ready for a future versioning endpoint without a migration.

## `processing_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK -> documents, `ON DELETE CASCADE` | |
| `job_type` | enum: `ingestion`, `reprocess` | |
| `status` | enum: `queued`, `running`, `retrying`, `completed`, `failed`, `cancelled` | the job's own execution lifecycle |
| `current_stage` | enum, same values as `documents.processing_status` | which pipeline stage this job was in when it last reported progress |
| `progress` | smallint | 0-100 |
| `retries`, `max_retries` | smallint | retry/backoff policy is enforced by the worker against these columns, not ARQ's own (in-memory, restart-unsafe) retry counter - see `app/worker/tasks.py` |
| `worker_id` | varchar(128), nullable | |
| `started_at`, `completed_at`, `failed_at` | timestamptz, nullable | |
| `execution_time_ms` | integer, nullable | |
| `error_message` | text, nullable | |
| `created_at`, `updated_at` | timestamptz | |

## `document_chunks`

Metadata plus (since Phase 5) a generated full-text-search column - real
vector embeddings live in the separate polymorphic `embeddings` table
below, not a column here (a chunk is only one of five embeddable source
types).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK -> documents, `ON DELETE CASCADE` | |
| `chunk_index` | integer | unique per `document_id`, sequential |
| `page_number` | integer, nullable | the page the chunk starts on |
| `text` | text | |
| `token_count` | integer | `tiktoken` (`cl100k_base`) |
| `metadata_json` | jsonb | `source_pages` (when a chunk spans pages) and `tables` (any pdfplumber-extracted table rows on the chunk's page) |
| `text_search` | tsvector, `GENERATED ALWAYS AS (to_tsvector('english', text)) STORED` | Phase 5: never written by the application - `BM25Search`'s `ts_rank_cd`/`websearch_to_tsquery` queries read it. GIN-indexed (`ix_document_chunks_text_search`) |
| `created_at`, `updated_at` | timestamptz | |

Every ingestion run **deletes and re-inserts** a document's chunks rather
than appending - re-running the pipeline (a retry or an explicit
`POST /documents/{id}/reprocess`) is idempotent by construction, never
duplicates chunks.

## `extraction_runs` (Phase 3.2)

One row per `POST /documents/{id}/extract` call - a separate lifecycle
from `processing_jobs`, so re-extracting with an updated prompt version
never requires redoing OCR/chunking. See ARCHITECTURE.md's extraction
pipeline section for why.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK -> documents, `ON DELETE CASCADE` | |
| `pipeline_version` | varchar(32) | this phase's pipeline code version (`"3.2.0"`), not a prompt version |
| `provider`, `model` | varchar(32), varchar(128) | which `LLMProvider`/model ran this pipeline (Phase 3.1) |
| `prompt_version` | varchar(32) | the primary (`document_understanding`) prompt's version; each agent's own version is in `metadata_json` since they can advance independently |
| `prompt_hash` | varchar(64) | SHA-256 of that prompt's actual wording (`PromptRegistry.compute_hash`) - proves what was sent to the model, independent of its version label |
| `extraction_fingerprint` | varchar(64), nullable, indexed | (Phase 3.3) `sha256(document.sha256_hash + prompt_hash + pipeline_version + provider + model)` - lets `trigger_extraction` recognize an identical prior extraction and return it instead of re-running the LLM pipeline. `null` on runs created before Phase 3.3. |
| `status` | enum: `pending`, `running`, `completed`, `failed` | |
| `started_at`, `completed_at` | timestamptz, nullable | |
| `processing_time_ms` | integer, nullable | |
| `token_usage` | jsonb | `{prompt_tokens, completion_tokens, total_tokens}` summed across every LLM-calling step |
| `estimated_cost` | float, nullable | `ProviderRegistry.estimate_cost_usd` - reference pricing, not billing-accurate (see ARCHITECTURE.md) |
| `retry_count` | smallint | summed `AgentStepResult.retries_used` across all pipeline steps - not a separate outer job-retry loop like `processing_jobs.retries` (see ARCHITECTURE.md's "Deltas") |
| `error_message` | text, nullable | |
| `metadata_json` | jsonb | per-agent prompt versions and other run detail |
| `created_at`, `updated_at` | timestamptz | |

## `extracted_entities` (Phase 3.2)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `extraction_run_id` | UUID FK -> extraction_runs, `ON DELETE CASCADE` | |
| `entity_type` | enum: `commodity`, `port`, `company`, `country`, `currency`, `price`, `contract`, `date`, `quantity`, `unit`, `incoterm`, `hs_code`, `organization`, `terminal`, `vessel` | |
| `raw_value` | text | exact text as extracted |
| `normalized_value` | text, nullable | the LLM's own self-reported normalization this phase - not independently validated (NormalizationAgent is a later phase) |
| `confidence` | float | the LLM's own self-reported certainty - not independently computed (ConfidenceAgent is a later phase) |
| `page_number` | integer, nullable | |
| `bounding_box` | jsonb, nullable | `{x0,y0,x1,y1}` in PDF points, real coordinates from a fresh PyMuPDF pass (`domain.ground_bounding_box`) - `null` when no confident text match was found, never a guess |
| `source_chunk` | UUID FK -> document_chunks, nullable, `ON DELETE SET NULL` | |
| `provider`, `model`, `prompt_version` | | which provider/model/prompt version produced this specific entity |
| `created_at`, `updated_at` | timestamptz | |

## `entity_mentions` (Phase 3.2)

1:1 with `extracted_entities` in this phase (each chunk-level extraction
produces its own entity row, so it has exactly one mention) - schema
supports many mentions per entity so a later phase's cross-chunk entity
resolution (NormalizationAgent merging repeated mentions into one
canonical entity) is additive, not a migration.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `entity_id` | UUID FK -> extracted_entities, `ON DELETE CASCADE` | |
| `page_number` | integer | |
| `character_offset` | integer, nullable | position within `source_chunk`'s text, via `domain.find_mention_context` - `null` if the LLM's raw_value doesn't appear verbatim |
| `surrounding_text` | text | a window around the match, or the raw_value itself if no match was found |
| `source_chunk` | UUID FK -> document_chunks, nullable, `ON DELETE SET NULL` | |

## `extracted_tables` (Phase 3.2)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `extraction_run_id` | UUID FK -> extraction_runs, `ON DELETE CASCADE` | |
| `page_number` | integer | |
| `title` | varchar(512), nullable | LLM-proposed caption |
| `confidence` | float | LLM's own self-reported confidence |
| `row_count`, `column_count` | integer | **real**, structural - from Phase 2's persisted table grid or a fresh pdfplumber pass, never asked of the LLM |
| `metadata_json` | jsonb | `bounding_box` (real, from a fresh `pdfplumber.find_tables()` pass - `TableGeometryExtractor`) |
| `created_at`, `updated_at` | timestamptz | |

## `table_cells` (Phase 3.2)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `table_id` | UUID FK -> extracted_tables, `ON DELETE CASCADE` | |
| `row`, `column` | integer | 0-indexed |
| `raw_value` | text, nullable | real, structural cell text |
| `normalized_value` | text, nullable | LLM-proposed normalization |
| `confidence` | float | |

Every extraction run **deletes and re-inserts** `extracted_entities`/
`extracted_tables` (and their children) scoped to its own
`extraction_run_id` before persisting - same idempotency pattern as
`document_chunks`, so a retried Persist step never duplicates rows.

## `trust_pipeline_runs` (Phase 3.3)

One row per `POST /extraction-runs/{id}/validate` call - its own lifecycle,
separate from `extraction_runs`, for the same reason `extraction_runs` is
separate from `processing_jobs`: re-validating (e.g. after a canonical
registry update) never requires re-running the LLM extraction. Not one of
the four tables the Phase 3.3 spec names explicitly - added because this
pipeline needs the same kind of "run" record `extraction_runs` is for
Phase 3.2, and because the spec's own observability requirements (average
confidence, review queue size, validation time) need somewhere to land.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `extraction_run_id` | UUID FK -> extraction_runs, `ON DELETE CASCADE` | |
| `pipeline_version` | varchar(32) | `"3.3.0"` |
| `rule_registry_version` | varchar(32) | which built-in rule set produced this run's findings - same provenance idea as `extraction_runs.prompt_hash` |
| `status` | enum: `pending`, `running`, `completed`, `failed` | own native Postgres type (`trust_pipeline_status`), deliberately not shared with `extraction_runs.status`'s `extraction_status` type - a downgrade of this table's migration can never risk the unrelated one |
| `started_at`, `completed_at` | timestamptz, nullable | |
| `processing_time_ms` | integer, nullable | |
| `retry_count` | smallint | |
| `error_message` | text, nullable | |
| `entities_validated` | integer | count of entities this run scored |
| `entities_flagged_for_review` | integer | count of `review_queue` rows this run created |
| `average_confidence` | float, nullable | mean `confidence_scores.overall_score` across the run |
| `created_at`, `updated_at` | timestamptz | |

## `validation_results` (Phase 3.3)

One row per rule evaluation - both entity-scoped (date, currency, quantity,
unit, HS code, Incoterm, exchange rate, bounding-box geometry) and
cross-entity (duplicate, conflicting values, table-total reconciliation).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `extraction_run_id` | UUID FK -> extraction_runs, `ON DELETE CASCADE` | |
| `entity_id` | UUID FK -> extracted_entities, nullable, `ON DELETE CASCADE` | `null` for cross-entity/cross-table findings with no single entity to attribute them to (e.g. a table's stated total not matching the sum of its rows) - the entities/table involved are named in `message` instead |
| `validation_rule` | varchar(128) | the rule's own id, e.g. `"currency.invalid_code"` |
| `validation_type` | enum: `date`, `currency`, `quantity`, `unit`, `duplicate`, `hs_code`, `incoterm`, `exchange_rate`, `geometry`, `consistency`, `conflict` | |
| `severity` | enum: `info`, `warning`, `error`, `critical` | |
| `passed` | boolean | |
| `message` | text | human-readable explanation, references ids/rule names only - never raw document content |
| `created_at` | timestamptz | write-once (a re-run deletes and re-inserts, see below) - no `updated_at` |

## `confidence_scores` (Phase 3.3)

One row per entity - `entity_id` is the table's own primary key (the
Phase 3.3 spec's field list for this table omits a surrogate `id`,
enforcing the 1:1 relationship in the schema itself). `table_score`/
`provider_score` are additive beyond the spec's literal 7-column list, to
cover `ConfidenceAgent`'s own named responsibilities ("table", "provider")
without dropping either dimension - see ARCHITECTURE.md.

| Column | Type | Notes |
|---|---|---|
| `entity_id` | UUID PK, FK -> extracted_entities, `ON DELETE CASCADE` | |
| `overall_score` | float | weighted average of the 8 dimensions below |
| `extraction_score` | float | the entity's own LLM-reported confidence (Phase 3.2) |
| `geometry_score` | float | 1.0 if `bounding_box` is grounded, 0.4 if not |
| `layout_score` | float | from `extraction_runs.metadata_json["layout_summary"]` - single- vs multi-column page |
| `table_score` | float | average confidence of tables on the entity's page |
| `consistency_score` | float | severity-weighted pass ratio of this entity's cross-entity findings (duplicate/conflict) |
| `normalization_score` | float | this entity's `normalization_results.confidence` |
| `validation_score` | float | severity-weighted pass ratio of this entity's own (non-cross-entity) findings |
| `provider_score` | float | static per-provider reliability prior, e.g. `groq: 0.85` - a calibratable starting point, not measured accuracy |
| `explanation_json` | jsonb | `{weights, components, validation_findings}` - a full breakdown, never a bare number |
| `created_at` | timestamptz | |

## `normalization_results` (Phase 3.3)

One row per entity - `entity_id` is the table's own primary key, same
reasoning as `confidence_scores`.

| Column | Type | Notes |
|---|---|---|
| `entity_id` | UUID PK, FK -> extracted_entities, `ON DELETE CASCADE` | |
| `canonical_id` | varchar(256), nullable | e.g. `"country:US"`, `"company:adani_ports_sez"` - `null` for value types (date/quantity/price), which have no identity to resolve, and for unresolved entities |
| `canonical_name` | varchar(256), nullable | |
| `normalized_value` | text, nullable | for identity types, the canonical name; for value types, the canonicalized value itself (an ISO date, a `"<value> <unit_canonical_id>"` pair, a `"<value> <currency_canonical_id>"` pair) |
| `normalization_method` | varchar(64) | `alias_lookup`, `slug_derived`, `slug_derived_fallback`, `prefix_lookup`, `format_normalized`, `literal_normalized`, `value_parsed`, or `unresolved` |
| `confidence` | float | `1.0` for an exact alias match, down to `0.0` for `unresolved` |
| `created_at` | timestamptz | |

## `review_queue` (Phase 3.3)

Backend only - no UI yet. One row per **entity**, not per trigger reason:
an entity flagged for multiple reasons (low confidence, a validation
failure, an unresolved canonical entity) gets a single row naming all of
them in `reason`, at the highest priority among them.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `extraction_run_id` | UUID FK -> extraction_runs, `ON DELETE CASCADE` | additive beyond the spec's literal field list - lets the API list a run's review items without joining through `entity_id` |
| `entity_id` | UUID FK -> extracted_entities, `ON DELETE CASCADE` | |
| `reason` | text | semicolon-joined summary of every trigger that fired |
| `priority` | enum: `low`, `medium`, `high`, `critical` | |
| `assigned_to` | UUID FK -> users, nullable, `ON DELETE SET NULL` | settable via `PATCH /review-queue/{id}`, no assignment UI yet |
| `status` | enum: `pending`, `in_review`, `resolved`, `dismissed` | |
| `resolution` | text, nullable | |
| `reviewed_at` | timestamptz, nullable | set when `status` moves to `resolved` or `dismissed` |
| `created_at` | timestamptz | |

Known scope boundary: `entity_id` is required, so a table-level finding
(e.g. `table.inconsistent_totals`, which has no single entity) is recorded
in `validation_results` for audit but cannot itself enter the review queue
this phase - see ARCHITECTURE.md's Deltas section.

Every trust pipeline run **deletes and re-inserts** `validation_results`/
`confidence_scores`/`normalization_results`/`review_queue` scoped to its
own `extraction_run_id` (the latter two via a subquery through
`extracted_entities`, since they carry no `extraction_run_id` column of
their own) before persisting - same idempotency pattern as
`extracted_entities`/`document_chunks`.

## `ontology_types` (Phase 4)

Reference/vocabulary data - the node types a `graph_nodes.node_type` may
declare. Seeded via Alembic data migration `59226041fb77`, not the app
(no create/update API - see ARCHITECTURE.md's reversal of Phase 3.3's
static-JSON precedent). 8 seeded rows: `company` (parented under
`organization`), `terminal` (parented under `port`), and
`organization`/`port`/`country`/`commodity`/`contract`/`vessel`
(top-level).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `entity_type` | varchar(64), unique | e.g. `"company"` - the identity-bearing subset of extraction's `EntityType` |
| `description` | text | |
| `parent_type` | varchar(64), nullable, self-FK -> `ontology_types.entity_type`, `ON DELETE SET NULL` | type hierarchy, e.g. `company` -> `organization` |
| `metadata_json` | jsonb | |

No `created_at`/`updated_at` - seed/reference data, not an event with a
meaningful insertion order.

## `relationship_types` (Phase 4)

Reference/vocabulary data - the relationship types a `graph_edges.
relationship_type` may declare, and their algebraic properties. Seeded
via the same migration as `ontology_types`. 10 seeded rows: the 6 the
built-in rules actually produce (`owns`, `operates`, `shipped_from`,
`shipped_to`, `references`, `located_in`) plus 4 inverse-only rows
(`owned_by`, `operated_by`, `referenced_by`, `contains`) that exist for
ontology completeness and future traversal use, never themselves written
to `graph_edges.relationship_type` by the current rules.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `relationship_name` | varchar(64), unique | e.g. `"owns"` |
| `inverse_relationship` | varchar(64), nullable, self-FK -> `relationship_types.relationship_name`, `ON DELETE SET NULL` | e.g. `owns` <-> `owned_by`; `NULL` for `shipped_from`/`shipped_to`, which have no modeled inverse |
| `symmetric` | boolean | none of the 10 seeded rows are symmetric (a country is not located in its own port) |
| `transitive` | boolean | `true` for `located_in`/`contains` (A in B, B in C => A in C); `false` for the rest |
| `metadata_json` | jsonb | |

## `graph_nodes` (Phase 4)

One row per **canonical identity**, not per entity - `canonical_id` is
Phase 3.3's `NormalizationResult.canonical_id`, unique. An entity only
becomes eligible for a node once it has resolved to one; unresolved
entities stay in the review queue, never enter the graph.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `canonical_id` | varchar(256), unique | e.g. `"company:adani_ports_sez"` |
| `node_type` | varchar(64), FK -> `ontology_types.entity_type`, `ON DELETE RESTRICT` | |
| `display_name` | varchar(512) | |
| `aliases_json` | jsonb (`list[str]`) | every raw text form observed for this identity, merged across documents |
| `metadata_json` | jsonb | |
| `status` | enum: `active`, `merged` | additive beyond the spec's literal field list |
| `merged_into_id` | UUID, nullable, self-FK -> `graph_nodes.id`, `ON DELETE SET NULL` | additive; set by `POST /graph/merge` - a tombstone, never deleted |
| `created_at`, `updated_at` | timestamptz | mutable (aliases/merge state change) - `TimestampMixin` |

## `graph_edges` (Phase 4)

One row per **distinct relationship**, cumulative across every
extraction run that ever contributed evidence for it - never
delete-then-recreated on rebuild, only upserted (see ARCHITECTURE.md).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_node_id` | UUID FK -> `graph_nodes.id`, `ON DELETE CASCADE` | |
| `target_node_id` | UUID FK -> `graph_nodes.id`, `ON DELETE CASCADE` | |
| `relationship_type` | varchar(64), FK -> `relationship_types.relationship_name`, `ON DELETE RESTRICT` | |
| `confidence` | float | `MAX` of every contributing finding's confidence - more evidence never lowers it, a weak duplicate never dilutes a strong original |
| `evidence_count` | integer | `COUNT(DISTINCT chunk_id)` among this edge's `graph_evidence` rows |
| `provenance_json` | jsonb | `{latest_document_id, latest_extraction_run_id, latest_evidence_type}` - a cheap summary; the full itemized trail is `graph_evidence` |
| `created_at`, `updated_at` | timestamptz | additive beyond the spec's literal field list: unlike Phase 3.3's fact tables, an edge is not append-only |

Unique on `(source_node_id, target_node_id, relationship_type)` -
`uq_graph_edges_source_target_relationship`.

## `graph_evidence` (Phase 4)

One row per **(edge, entity mention)** that justified an edge - two rows
per detected relationship instance (source-side entity, target-side
entity), since the spec's own field list gives a single `entity_id`
column but a relationship connects two (see ARCHITECTURE.md).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `edge_id` | UUID FK -> `graph_edges.id`, `ON DELETE CASCADE` | |
| `document_id` | UUID FK -> `documents.id`, `ON DELETE CASCADE` | |
| `extraction_run_id` | UUID FK -> `extraction_runs.id`, `ON DELETE CASCADE` | |
| `entity_id` | UUID FK -> `extracted_entities.id`, `ON DELETE CASCADE` | |
| `page_number` | integer, nullable | |
| `chunk_id` | UUID, nullable, FK -> `document_chunks.id`, `ON DELETE SET NULL` | |
| `prompt_hash` | varchar(64) | the extraction run's own `prompt_hash`, for provenance |
| `created_at` | timestamptz | write-once |

Unique on `(edge_id, entity_id, chunk_id)` -
`uq_graph_evidence_edge_entity_chunk` - the idempotent-rebuild dedup key:
re-running a build on unchanged data never creates a duplicate evidence
row or inflates `evidence_count`.

## `graph_build_runs` (Phase 4)

One row per `POST /graph/rebuild` call - not one of the spec's literal 5
tables, added for the same reason `trust_pipeline_runs` was in Phase
3.3: the "run" record this pipeline needs (status/timing/error
tracking), since the endpoint enqueues an ARQ job that needs polling.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `extraction_run_id` | UUID, nullable, FK -> `extraction_runs.id`, `ON DELETE SET NULL` | `NULL` = full-corpus rebuild; set = scoped to one extraction run's entities (still upserted against the whole graph) |
| `status` | enum: `pending`, `running`, `completed`, `failed` | own native Postgres type (`graph_build_status`), same reasoning as `trust_pipeline_status` - deliberately not shared with `extraction_runs.status`'s type |
| `started_at`, `completed_at` | timestamptz, nullable | |
| `processing_time_ms` | integer, nullable | |
| `retry_count` | integer | |
| `error_message` | text, nullable | on a full-corpus sweep, set even when earlier runs in the sweep succeeded and were persisted - see ARCHITECTURE.md's partial-failure handling |
| `runs_processed` | integer | how many extraction runs this build actually processed |
| `nodes_created`, `nodes_updated`, `edges_created`, `edges_updated`, `evidence_created` | integer | |
| `created_at`, `updated_at` | timestamptz | |

Only one `graph_build_run` may be `pending`/`running` at a time (checked
by `GraphService.trigger_rebuild`, enforced at the application layer -
the graph is one shared structure, unlike trust's per-`extraction_run_id`
concurrency scoping).

## `embeddings` (Phase 5)

One row per (source, provider, model) - a polymorphic vector store
covering all five embeddable source types (`document_chunk`, `graph_node`,
`graph_edge`, `canonical_entity`, `ontology_definition`). No FK on
`source_id`: two of the five source types have no database row at all
(`canonical_entity`/`ontology_definition` - see ARCHITECTURE.md), so
`source_id` is a plain string, not a UUID, and there is deliberately no
foreign-key constraint - the standard tradeoff any polymorphic-association
table makes.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_type` | enum: `document_chunk`, `graph_node`, `graph_edge`, `canonical_entity`, `ontology_definition` | own native Postgres type (`embedding_source_type`) |
| `source_id` | varchar(256) | `str(uuid)` for chunk/node/edge; the natural string key (`canonical_id` / `entity_type`) for canonical_entity/ontology_definition |
| `embedding_provider` | varchar(32) | |
| `embedding_model` | varchar(128) | |
| `embedding_dimension` | integer | |
| `embedding_hash` | varchar(64) | sha256 of the exact text embedded - checked before ever calling the provider, so identical content is never re-embedded |
| `embedding_vector` | `vector(1536)` (pgvector) | fixed width, chosen to match `openai/text-embedding-3-small` - see ARCHITECTURE.md for the tradeoff and the migration path to change it |
| `created_at`, `updated_at` | timestamptz | updated in place when content changes (hash differs), not append-only |

Unique on `(source_type, source_id, embedding_provider, embedding_model)` -
`uq_embeddings_source_provider_model`. HNSW index
`ix_embeddings_vector_cosine_hnsw` (`vector_cosine_ops`) built by default;
L2/inner-product distance remain queryable ad hoc via `VectorSearch`, just
unindexed - a disclosed, deliberate scope decision, not an oversight.

## `retrieval_runs` (Phase 5)

One row per `HybridRetriever` invocation (`POST /retrieve`,
`/retrieve/context`, or `/retrieve/graph`) - the "run" record
`GET /retrieval-runs/{id}` reads back, same pattern as
`extraction_runs`/`trust_pipeline_runs`/`graph_build_runs`.
`status`/`error_message`/`requested_by_user_id` are additive beyond the
spec's literal field list, for the same reason `graph_build_runs` added
fields beyond its own spec: every other "run" table in this codebase
carries a status and who triggered it.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `query` | text | |
| `provider`, `embedding_model` | varchar, nullable | null when the run degraded to BM25+graph-only (no embedding provider configured) - see ARCHITECTURE.md |
| `reranker` | varchar(64), nullable | `"weighted_linear"` - `RerankerService`'s strategy name |
| `latency_ms` | integer, nullable | |
| `total_candidates` | integer | before top-K truncation |
| `retrieved_results` | integer | after top-K truncation |
| `status` | enum: `pending`, `running`, `completed`, `failed` | own native Postgres type (`retrieval_run_status`) |
| `error_message` | text, nullable | |
| `requested_by_user_id` | UUID, nullable, FK -> `users.id`, `ON DELETE SET NULL` | |
| `created_at`, `updated_at` | timestamptz | |

## `retrieval_results` (Phase 5)

One row per ranked item in a completed retrieval run - write-once, no
`updated_at` (matches `graph_evidence`'s simpler shape, not
`retrieval_runs`' mutable-status shape).

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `retrieval_run_id` | UUID FK -> `retrieval_runs.id`, `ON DELETE CASCADE` | |
| `source_type` | enum: same 5 values as `embeddings.source_type` | own native Postgres type (`retrieval_result_source_type`) - deliberately not shared with `embeddings.source_type`'s type, same reasoning as `graph_build_status`/`extraction_status` |
| `source_id` | varchar(256) | |
| `retrieval_method` | enum: `bm25`, `vector`, `graph_expansion`, `hybrid` | own native Postgres type (`retrieval_method`); `hybrid` means the candidate was found by more than one method |
| `score` | float | the raw method score used for initial merge/dedup |
| `rerank_score` | float, nullable | `RerankerService`'s final weighted score |
| `final_rank` | integer | 1-indexed |
| `created_at` | timestamptz | |

## Timestamp defaults: `clock_timestamp()`, not `now()`

Every `created_at`/`updated_at` column defaults to `clock_timestamp()`,
not `now()`. In Postgres, `now()` is frozen at transaction start, so
multiple rows inserted in the same transaction get an **identical**
timestamp - this surfaced as a real, reproducible test failure
(`test_list_orders_by_created_at_descending`) before the fix, not a
theoretical concern. `clock_timestamp()` reads the actual wall clock at
statement execution, so rows are always orderable by insertion order even
within one transaction.

## Naming convention

All indexes/constraints follow an explicit naming convention (set in
`app/core/database.py`'s `NAMING_CONVENTION`) so Alembic autogenerate diffs
stay stable across renames: `pk_<table>`, `uq_<table>_<column>`,
`fk_<table>_<column>_<referred_table>`, `ix_<column_label>`,
`ck_<table>_<constraint_name>`.
