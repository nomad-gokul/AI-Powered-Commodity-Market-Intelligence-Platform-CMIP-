# CMIP Data-Engineering Benchmarks

Benchmarks of CMIP's **data pipeline and storage layer**: ingestion
throughput, OCR cost and quality, idempotent loads, deduplication and
incremental processing, full-text and vector indexing, and knowledge-graph
load and traversal.

The ingestion benchmark drives **the project's own Phase 2 code**: it imports
`PDFExtractor`, `TesseractOCRProvider`, `TableExtractor` and `DocumentChunker`
from `backend/app` rather than reimplementing them. The database benchmark
uses table definitions that mirror the Alembic migrations (generated
`tsvector` column + GIN index, the graph's natural-key unique constraints, a
`vector(1536)` HNSW index with `m=16, ef_construction=64`). Its full-text and
traversal SQL is copied verbatim from `retrieval/bm25.py` and
`graph/repository.py`.

> **Run environment:** 2-vCPU Intel Xeon @ 2.10 GHz sandbox, 7 GB RAM,
> PostgreSQL 16.15, pgvector 0.6.0, Tesseract (system package), Python 3.13.
> All data is **synthetic** (seeded, reproducible); see *Limitations*.

---

## Headline results

| Area | Result |
|---|---|
| Ingestion throughput | **4.9 pages/s** with 1 worker → **9.4 pages/s** with 2 workers (**1.92×**, near-linear) on 480 pages / 99 MB |
| Where the time goes | OCR on scanned pages takes **65.9 %** of processing time, although only **9.4 %** of pages are scanned |
| OCR vs native text | **1,427 ms/page** (OCR) vs **25 ms/page** (native PyMuPDF text): **~57×**, which is why OCR is a per-page fallback only |
| OCR data quality | 45/45 scanned pages correctly routed to OCR. Word recall **99.5 %**, **numeric-token recall 97.4 %** (min 87.9 % on a page) |
| Ingest validation | Streaming size-guard + SHA-256 in one pass: **~1.2 GB/s**, negligible (0.1 % of time) |
| Chunking | 500 chunks, mean 397 tokens (p95 495, max 530 ≤ 500+75 cap). Re-chunking is **byte-identical** (deterministic) |
| Idempotent reload | 3 delete-then-insert re-runs → **500 rows every time**. A naive append is **rejected by the natural-key unique constraint** |
| Incremental embeddings | Unchanged re-run: **0 of 500** chunks re-embedded. 5 % edited: **25 of 500**, so **95 % of embedding work skipped** |
| Bulk load | COPY 4,077 rows/s vs batched INSERT 3,677 vs row-by-row commit 1,202. The generated `tsvector` column dominates write cost (**16×**), not the GIN index |
| Full-text, exact lookups | 200k chunks: **0.5 ms** with GIN vs 221 ms seq-scan (**~420×**) vs 1,564 ms `ILIKE '%…%'` |
| Full-text, broad topics | Queries matching ~14 % of rows: p50 203 ms with GIN vs 292 ms without; ranking all matches dominates |
| Graph load | Set-based `INSERT … ON CONFLICT` upserts 25k findings in **1.08 s** vs **10.8 s** per-row (**~10×**), **identical final graph**, re-runs are no-ops |
| Graph traversal (depth 6) | Project setup: p50 **7.6 s**, 2/5 queries hit the 20 s timeout → with a `target_node_id` index + frontier BFS: p50 **179 ms**, p95 **375 ms** |
| Vector search | 20k × 1536-d: HNSW **1.9 ms** vs exact **115 ms** (**~60×**), recall@10 = 1.00 on this (synthetic, clustered) data. Index 164 MB, built in 13.6 s |

![Where ingestion time goes](results/charts/1_ingestion_stage_share.png)
![Worker scaling](results/charts/2_worker_scaling.png)

---

## 1. Ingestion pipeline (`bench_ingestion.py`)

Runs each document through the same stage order as
`app/worker/tasks.py::_run_pipeline`: read → streaming size-guard + SHA-256 →
text extraction (native first, Tesseract OCR fallback below 20 chars/page,
200 DPI) → pdfplumber table extraction → 500/75-token chunking.

**Findings**
- **OCR is the bottleneck.** About 9 % of pages consume about 66 % of
  processing time. This confirms the design choice to OCR only pages without
  a text layer. OCR'ing everything would cost about 57× more per native page.
- **OCR output is good but not perfect for numbers.** Word recall is 99.5 %,
  but numeric recall averages 97.4 % and drops to 87.9 % on the worst page.
  For a price report, numbers are the data that matters. This is the case
  for the project's downstream trust layer (validation rules, confidence
  scoring, human review queue) rather than trusting OCR text as-is.
- **Table extraction is the second-biggest cost (21.6 %).** 216 tables were
  detected out of 240 generated. That gap is consistent with tables that sit
  on scanned pages: pdfplumber needs a text layer, so those tables are lost.
  OCR-based table recognition would close it.
- **Horizontal scaling works.** The pipeline is CPU-bound and stateless per
  document, so adding worker processes scales near-linearly (1.92× on 2
  cores). ARQ workers scale the same way, across containers.

## 2. Loads, idempotency, incremental processing (`bench_database.py`)

- **Idempotent reloads:** the worker's pattern (`DELETE … WHERE document_id`
  then bulk insert) converges to exactly 500 rows across 3 re-runs, with an
  identical content checksum. Appending duplicates is impossible because
  `UNIQUE (document_id, chunk_index)` rejects it. Idempotency is enforced by
  the schema, not just by code.
- **Bulk-load cost lives in the generated column.** Loading with the
  `tsvector` column takes 4.34 s for 20k rows. Building the GIN index
  afterwards takes 0.52 s. Without the column, COPY runs at 65.7k rows/s.
  English stemming per row is the real write cost. Even so, about 4k
  chunks/s is several hundred times faster than ingestion produces chunks
  (about 1 chunk per page at under 10 pages/s), so the database write path
  is not the bottleneck.
- **Content-hash change detection** (`EmbeddingService.content_hash`):
  re-running ingestion on unchanged data sends nothing to the embedding API.
  Editing 5 % of chunks re-embeds exactly those 25.

![Full-text search](results/charts/3_full_text_search.png)

## 3. Search indexes

- **GIN full-text index:** for selective lookups (a contract number), the
  index answers in about 0.5 ms versus 221 ms for a sequential scan and
  1.56 s for `ILIKE`.
- **Broad topic queries are a known weak spot.** A query matching about 28k
  rows (14 % of the table) gets little help from the index, because
  `ts_rank_cd` has to score every match before `LIMIT 50`. p95 reached about
  1.8 s, worse than a sequential scan's 0.9 s, because the bitmap heap scan
  touches many pages. Mitigations: cap candidates before ranking, or rely on
  the hybrid retriever's vector branch for broad semantic queries.
- **HNSW vector index:** about 60× faster than an exact scan at 20k vectors,
  with perfect recall@10 on this data. The index is 164 MB for 20k × 1536-d,
  and memory grows linearly with the corpus. At scale that drives either a
  dedicated vector store or smaller/quantized embeddings.

![Vector search](results/charts/6_vector_search.png)

## 4. Knowledge graph

![Graph upsert](results/charts/5_graph_upsert.png)

- **Upserts:** the project's `PersistGraphResultsAgent` looks up each edge by
  its natural key, then inserts or updates it. That's a few round trips per
  finding. Staging the findings with COPY and running set-based
  `INSERT … ON CONFLICT DO UPDATE SET confidence = GREATEST(…)` produces the
  **identical** edges, evidence rows, `evidence_count`s and confidences,
  **about 10× faster**. Both approaches are idempotent: a re-run changes
  nothing.

![Graph traversal](results/charts/4_graph_traversal.png)

- **Traversal** on a 20k-node / 40k-edge scale-free graph (a few hub
  ports/companies, many leaves), 5 start nodes per depth, using the
  project's exact recursive CTE:
  - **Missing index.** The migration creates only the composite
    `UNIQUE (source_node_id, target_node_id, relationship_type)` index. The
    traversal matches `source = x OR target = x`, so the target side has no
    usable index. Adding `CREATE INDEX ON graph_edges (target_node_id)` cuts
    depth-4 p50 from 120 ms to 7 ms and depth-6 p50 from 7.6 s to 393 ms.
  - **Path explosion.** The CTE tracks a per-path visited array, so it
    enumerates every simple path, not every node. At depth 6 it enumerates
    about 401k paths to reach about 18k distinct nodes. A level-by-level BFS
    with a global visited set returns **identical results** in every
    comparison where the CTE finished (58 of 60), with p95 375 ms vs
    2,958 ms at depth 6.
  - Without the index, 2 of 5 depth-6 queries exceeded the 20 s statement
    timeout. The reported depth-6 p50/p95 for that variant covers only the
    3 that finished, so the true tail is worse.

---

## What the benchmarks recommend

1. **Add an index on `graph_edges(target_node_id)`.** It's a one-line
   migration and gives 10–20× faster deep traversals.
2. **Replace path-enumerating traversal with frontier BFS** (or cap depth
   at 4 for interactive calls). p95 at depth 5–6 drops 2.5–8×.
3. **Make the graph upsert set-based** (COPY to a staging table, then
   `INSERT … ON CONFLICT`). About 10× faster with the same semantics.
4. **Scale OCR separately.** It dominates cost, so route scanned pages to a
   dedicated OCR worker pool (or a GPU / cloud OCR) and keep native-text
   documents on the fast path.
5. **Guard broad full-text queries.** Cap candidates before `ts_rank_cd`,
   and lean on the vector branch for topic-level queries.

## Limitations (read before quoting numbers)

- **Synthetic data.** Reports are generated from templates with a small
  vocabulary, which makes topic terms unusually common. Real report text
  will have different selectivity. Vectors are synthetic clustered
  embeddings, not model outputs, so the recall@10 of 1.00 is optimistic.
  Real-embedding recall is typically somewhat lower and should be
  re-measured.
- **Small sandbox.** 2 vCPUs and a local Postgres. Absolute numbers will
  differ on other hardware; the ratios and scaling trends are the
  meaningful part.
- **pgvector 0.6.0** was used here; the project's Docker image ships a newer
  pgvector. HNSW behaviour is the same, but speed may differ.
- **Not measured:** the LLM extraction step (needs a paid API key, and is
  network-bound rather than a data-engineering cost) and end-to-end API
  latency.
- The upsert comparison reimplements the agent's per-row access pattern in
  raw SQL, without the ORM's overhead, so the real gap is likely somewhat
  larger.

## Reproduce

```bash
cd benchmarks
pip install -r requirements.txt            # plus a system Tesseract install
python gen_corpus.py --out corpus --docs 60 --pages 8 --scanned-ratio 0.1
python bench_ingestion.py --corpus corpus --backend ../backend --out results --workers 1 2

# a scratch database on the project's own Postgres (docker compose up postgres)
docker compose exec postgres createdb -U cmip cmip_bench
docker compose exec postgres psql -U cmip -d cmip_bench -c "CREATE EXTENSION vector"
python bench_database.py --dsn postgresql://cmip:cmip_dev_password@localhost:5544/cmip_bench \
       --chunks results/chunks.jsonl --out results
python make_charts.py results
```

Raw numbers: `results/ingestion_summary.json`, `results/database_summary.json`.
