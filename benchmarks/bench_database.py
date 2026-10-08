"""Database-layer benchmarks for CMIP's storage design, on PostgreSQL 16 +
pgvector. Table definitions mirror the project's Alembic migrations
(document_chunks with its GENERATED tsvector + GIN index; graph_edges with
its (source, target, relationship_type) unique key; graph_evidence with its
(edge, entity, chunk) unique key; embeddings vector(1536) with an HNSW
cosine index, m=16, ef_construction=64). SQL for full-text search and graph
traversal is copied verbatim from retrieval/bm25.py and graph/repository.py.

Sections (each prints and saves its own JSON):
  1. bulk_load       - row-by-row vs batched INSERT vs COPY, and the write cost
                       of the generated tsvector + GIN index
  2. idempotent_load - delete-then-insert re-runs converge; naive append is
                       rejected by the natural-key unique constraint
  3. full_text       - GIN-indexed websearch_to_tsquery/ts_rank_cd vs seq scan vs ILIKE
  4. graph_upsert    - per-row ORM-style upsert vs set-based INSERT ... ON CONFLICT;
                       re-run idempotency of edges/evidence/evidence_count
  5. traversal       - the project's recursive CTE vs level-by-level frontier BFS,
                       with and without an index on target_node_id
  6. vector          - HNSW vs exact scan: build time, latency, recall@10
  7. incremental     - content-hash change detection: how much embedding work is skipped

Usage: python bench_database.py --dsn postgresql://postgres:bench@localhost/cmip_bench \
         --chunks results/chunks.jsonl --out results
"""

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
import uuid
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
from gen_corpus import paragraph  # noqa: E402  (same synthetic text generator as the PDFs)

RESULTS: dict = {}


def timed(fn, repeat: int = 1) -> list[float]:
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return out


def pctl(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def ms(values: list[float]) -> dict:
    return {"p50_ms": 1000 * pctl(values, 50), "p95_ms": 1000 * pctl(values, 95),
            "mean_ms": 1000 * statistics.mean(values)}


CHUNKS_DDL = """
CREATE TABLE document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    page_number integer,
    text text NOT NULL,
    token_count integer NOT NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}',
    {tsv}
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_document_chunks_document_id_chunk_index UNIQUE (document_id, chunk_index)
);
"""
TSV_COL = "text_search tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,"


def make_rows(n: int, seed: int = 7) -> list[tuple]:
    rng = random.Random(seed)
    rows, doc = [], uuid.uuid4()
    for i in range(n):
        if i % 50 == 0:
            doc = uuid.uuid4()
        text = "\n\n".join(paragraph(rng) for _ in range(rng.randint(3, 5)))
        # high-cardinality identifiers, as real reports have (vessels, contract numbers)
        text += (f" Cargo loaded on vessel MV{rng.randint(10000, 99999)} under contract "
                 f"CTR{rng.randint(100000, 999999)}.")
        rows.append((doc, i % 50, rng.randint(1, 8), text, len(text.split())))
    return rows


def reset_chunks(conn, with_tsv: bool) -> None:
    conn.execute("DROP TABLE IF EXISTS document_chunks CASCADE")
    conn.execute(CHUNKS_DDL.replace("{tsv}", TSV_COL if with_tsv else ""))
    if with_tsv:
        conn.execute("CREATE INDEX ix_document_chunks_text_search ON document_chunks "
                     "USING gin (text_search)")
    conn.commit()


INSERT_SQL = ("INSERT INTO document_chunks (document_id, chunk_index, page_number, text, token_count) "
              "VALUES (%s, %s, %s, %s, %s)")


def copy_rows(conn, rows) -> None:
    with conn.cursor() as cur:
        with cur.copy("COPY document_chunks (document_id, chunk_index, page_number, text, "
                      "token_count) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
    conn.commit()


# ---------------------------------------------------------------- 1. bulk load
def bench_bulk_load(conn) -> None:
    rows = make_rows(20_000)
    res = {"rows": len(rows)}

    reset_chunks(conn, True)
    sample = rows[:2_000]
    t = time.perf_counter()
    for r in sample:  # one statement + one commit per row: the anti-pattern
        conn.execute(INSERT_SQL, r)
        conn.commit()
    res["row_by_row_commit_rows_per_sec"] = len(sample) / (time.perf_counter() - t)

    reset_chunks(conn, True)
    t = time.perf_counter()
    with conn.cursor() as cur:  # batched executemany in one transaction (~ORM add_all+flush)
        cur.executemany(INSERT_SQL, rows)
    conn.commit()
    res["batched_insert_rows_per_sec"] = len(rows) / (time.perf_counter() - t)

    reset_chunks(conn, True)
    t = time.perf_counter()
    copy_rows(conn, rows)
    res["copy_rows_per_sec"] = len(rows) / (time.perf_counter() - t)

    # bulk-load pattern: keep the generated column, but build the GIN index AFTER the load
    reset_chunks(conn, True)
    conn.execute("DROP INDEX ix_document_chunks_text_search")
    conn.commit()
    t = time.perf_counter()
    copy_rows(conn, rows)
    t_mid = time.perf_counter()
    conn.execute("CREATE INDEX ix_document_chunks_text_search ON document_chunks "
                 "USING gin (text_search)")
    conn.commit()
    res["copy_then_build_gin_rows_per_sec"] = len(rows) / (time.perf_counter() - t)
    res["copy_then_build_gin_split_seconds"] = {"copy_with_tsvector": t_mid - t,
                                                "gin_build": time.perf_counter() - t_mid}

    reset_chunks(conn, False)
    t = time.perf_counter()
    copy_rows(conn, rows)
    res["copy_without_tsvector_gin_rows_per_sec"] = len(rows) / (time.perf_counter() - t)
    res["tsvector_gin_write_overhead_x"] = (res["copy_without_tsvector_gin_rows_per_sec"]
                                            / res["copy_rows_per_sec"])
    RESULTS["bulk_load"] = res
    print("bulk_load", json.dumps(res, indent=1))


# ------------------------------------------------------- 2. idempotent reload
def bench_idempotent(conn, chunks_path: Path) -> None:
    reset_chunks(conn, True)
    real = [json.loads(line) for line in chunks_path.open()]
    by_doc: dict[str, list[dict]] = {}
    for c in real:
        by_doc.setdefault(c["sha256"], []).append(c)
    doc_ids = {sha: uuid.uuid5(uuid.NAMESPACE_URL, sha) for sha in by_doc}

    def ingest_all() -> None:  # same pattern as worker/tasks.py: delete_for_document + bulk_create
        with conn.cursor() as cur:
            for sha, chunks in by_doc.items():
                cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc_ids[sha],))
                cur.executemany(INSERT_SQL, [(doc_ids[sha], c["index"], c["page"], c["text"],
                                              c["tokens"]) for c in chunks])
        conn.commit()

    counts, durations = [], []
    for _ in range(3):
        durations.append(timed(ingest_all)[0])
        counts.append(conn.execute("SELECT count(*) FROM document_chunks").fetchone()[0])
    content_sig = conn.execute(
        "SELECT md5(string_agg(document_id::text || chunk_index || md5(text), ',' "
        "ORDER BY document_id, chunk_index)) FROM document_chunks").fetchone()[0]

    naive_rejected = False
    try:  # appending the same chunks again without the delete
        first = next(iter(by_doc))
        c = by_doc[first][0]
        conn.execute(INSERT_SQL, (doc_ids[first], c["index"], c["page"], c["text"], c["tokens"]))
        conn.commit()
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        naive_rejected = True

    res = {"documents": len(by_doc), "real_chunks": len(real), "row_count_after_each_run": counts,
           "converged": len(set(counts)) == 1 and counts[0] == len(real),
           "content_signature_md5": content_sig,
           "reload_seconds_each_run": durations,
           "naive_append_rejected_by_unique_constraint": naive_rejected}
    RESULTS["idempotent_load"] = res
    print("idempotent_load", json.dumps(res, indent=1))


# ----------------------------------------------------------- 3. full-text search
BM25_SQL = """
SELECT id, document_id,
       ts_rank_cd(text_search, websearch_to_tsquery('english', %(q)s)) AS score
FROM document_chunks
WHERE text_search @@ websearch_to_tsquery('english', %(q)s)
ORDER BY score DESC
LIMIT 50
"""
QUERIES = ['"refinery maintenance" naphtha', "thermal coal Mundra", "Glencore copper Qingdao",
           "export quota urea", "LNG -diesel Fujairah", '"monsoon-related port congestion"',
           "iron ore Port Hedland BHP", "sanctions shipments Brent", "palm oil Santos Cargill",
           "jet fuel Rotterdam Shell"]


def bench_full_text(conn, n_rows: int) -> None:
    reset_chunks(conn, True)
    copy_rows(conn, make_rows(n_rows, seed=11))
    conn.execute("ANALYZE document_chunks")
    conn.commit()
    rng = random.Random(12)
    sample = conn.execute("SELECT text FROM document_chunks TABLESAMPLE SYSTEM (1)").fetchall()
    contracts = [t[0].split("contract ")[-1].rstrip(".") for t in rng.sample(sample, 10)]
    res = {"rows": n_rows}

    def run(sql, queries, setup="", params_fn=lambda q: {"q": q}, repeat=5):
        lat = []
        for q in queries:
            with conn.cursor() as cur:
                if setup:
                    cur.execute(setup)
                for _ in range(repeat):
                    t = time.perf_counter()
                    cur.execute(sql, params_fn(q))
                    cur.fetchall()
                    lat.append(time.perf_counter() - t)
            conn.rollback()  # discards SET LOCAL
        return lat

    def matches(q):
        return conn.execute("SELECT count(*) FROM document_chunks WHERE text_search @@ "
                            "websearch_to_tsquery('english', %s)", (q,)).fetchone()[0]

    no_index = "SET LOCAL enable_bitmapscan = off; SET LOCAL enable_indexscan = off"
    for label, queries in (("selective_identifier_queries", contracts),
                           ("broad_topic_queries", QUERIES)):
        plan = conn.execute("EXPLAIN " + BM25_SQL, {"q": queries[0]}).fetchall()
        group = {
            "queries": len(queries),
            "matching_rows_mean": statistics.mean(matches(q) for q in queries),
            "plan_uses_gin": any("ix_document_chunks_text_search" in r[0] for r in plan),
            "gin_indexed": ms(run(BM25_SQL, queries)),
            "seq_scan_no_index": ms(run(BM25_SQL, queries, no_index, repeat=2)),
        }
        group["speedup_gin_vs_seqscan_p50_x"] = (group["seq_scan_no_index"]["p50_ms"]
                                                 / group["gin_indexed"]["p50_ms"])
        res[label] = group
    # exact-identifier lookup the naive way: substring scan over raw text
    res["selective_identifier_queries"]["ilike_substring_scan"] = ms(run(
        "SELECT id FROM document_chunks WHERE text ILIKE %(p)s", contracts,
        params_fn=lambda q: {"p": f"%{q}%"}, repeat=2))
    res["table_mb"] = conn.execute(
        "SELECT pg_total_relation_size('document_chunks')/1e6").fetchone()[0]
    res["gin_index_mb"] = conn.execute(
        "SELECT pg_relation_size('ix_document_chunks_text_search')/1e6").fetchone()[0]
    RESULTS["full_text"] = res
    print("full_text", json.dumps(res, indent=1, default=float))


# ------------------------------------------------------------ 4. graph upsert
GRAPH_DDL = """
DROP TABLE IF EXISTS graph_evidence, graph_edges, graph_nodes CASCADE;
CREATE TABLE graph_nodes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_id varchar(256) NOT NULL UNIQUE,
    node_type varchar(64) NOT NULL);
CREATE TABLE graph_edges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relationship_type varchar(64) NOT NULL,
    confidence double precision NOT NULL,
    evidence_count integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_graph_edges_source_target_relationship
        UNIQUE (source_node_id, target_node_id, relationship_type));
CREATE TABLE graph_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_id uuid NOT NULL REFERENCES graph_edges(id) ON DELETE CASCADE,
    entity_id uuid NOT NULL,
    chunk_id uuid,
    CONSTRAINT uq_graph_evidence_edge_entity_chunk UNIQUE (edge_id, entity_id, chunk_id));
"""
REL_TYPES = ["owns", "operates", "shipped_from", "shipped_to", "located_in", "references"]


def make_findings(n_nodes: int, n_findings: int, seed: int = 3) -> tuple[list[str], list[tuple]]:
    rng = random.Random(seed)
    nodes = [f"entity:{i:06d}" for i in range(n_nodes)]
    findings = []
    for _ in range(n_findings):
        a, b = rng.sample(range(n_nodes), 2)
        findings.append((nodes[a], nodes[b], rng.choice(REL_TYPES), round(rng.uniform(0.3, 0.95), 3),
                         str(uuid.UUID(int=rng.getrandbits(128))),   # entity id
                         str(uuid.UUID(int=rng.getrandbits(128)))))  # chunk id
    return nodes, findings


def load_nodes(conn, nodes: list[str]) -> None:
    with conn.cursor() as cur:
        with cur.copy("COPY graph_nodes (canonical_id, node_type) FROM STDIN") as cp:
            for n in nodes:
                cp.write_row((n, "company"))
    conn.commit()


def upsert_per_row(conn, findings) -> None:
    """Shape of PersistGraphResultsAgent: lookup by natural key, then create or
    update; evidence checked against existing keys before insert."""
    ids = dict(conn.execute("SELECT canonical_id, id FROM graph_nodes").fetchall())
    with conn.cursor() as cur:
        for s, t, rel, conf, ent, chunk in findings:
            cur.execute("SELECT id, confidence FROM graph_edges WHERE source_node_id=%s AND "
                        "target_node_id=%s AND relationship_type=%s", (ids[s], ids[t], rel))
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO graph_edges (source_node_id, target_node_id, "
                            "relationship_type, confidence) VALUES (%s,%s,%s,%s) RETURNING id",
                            (ids[s], ids[t], rel, conf))
                edge_id = cur.fetchone()[0]
            else:
                edge_id = row[0]
                cur.execute("UPDATE graph_edges SET confidence=%s, updated_at=clock_timestamp() "
                            "WHERE id=%s", (max(row[1], conf), edge_id))
            cur.execute("SELECT 1 FROM graph_evidence WHERE edge_id=%s AND entity_id=%s AND "
                        "chunk_id=%s", (edge_id, ent, chunk))
            if cur.fetchone() is None:
                cur.execute("INSERT INTO graph_evidence (edge_id, entity_id, chunk_id) "
                            "VALUES (%s,%s,%s)", (edge_id, ent, chunk))
        cur.execute("UPDATE graph_edges e SET evidence_count = sub.c FROM (SELECT edge_id, "
                    "count(DISTINCT chunk_id) c FROM graph_evidence GROUP BY edge_id) sub "
                    "WHERE sub.edge_id = e.id AND e.evidence_count <> sub.c")
    conn.commit()


def upsert_set_based(conn, findings) -> None:
    """Same semantics in 4 set-based statements: stage -> ON CONFLICT upserts."""
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE stage (s text, t text, rel text, conf float8, "
                    "ent uuid, chunk uuid) ON COMMIT DROP")
        with cur.copy("COPY stage FROM STDIN") as cp:
            for f in findings:
                cp.write_row(f)
        cur.execute("""
            INSERT INTO graph_edges (source_node_id, target_node_id, relationship_type, confidence)
            SELECT ns.id, nt.id, st.rel, max(st.conf)
            FROM stage st JOIN graph_nodes ns ON ns.canonical_id = st.s
                          JOIN graph_nodes nt ON nt.canonical_id = st.t
            GROUP BY ns.id, nt.id, st.rel
            ON CONFLICT ON CONSTRAINT uq_graph_edges_source_target_relationship
            DO UPDATE SET confidence = GREATEST(graph_edges.confidence, EXCLUDED.confidence),
                          updated_at = clock_timestamp()
            WHERE EXCLUDED.confidence > graph_edges.confidence""")
        cur.execute("""
            INSERT INTO graph_evidence (edge_id, entity_id, chunk_id)
            SELECT DISTINCT e.id, st.ent, st.chunk
            FROM stage st JOIN graph_nodes ns ON ns.canonical_id = st.s
                          JOIN graph_nodes nt ON nt.canonical_id = st.t
                          JOIN graph_edges e ON e.source_node_id = ns.id
                                AND e.target_node_id = nt.id AND e.relationship_type = st.rel
            ON CONFLICT ON CONSTRAINT uq_graph_evidence_edge_entity_chunk DO NOTHING""")
        cur.execute("UPDATE graph_edges e SET evidence_count = sub.c FROM (SELECT edge_id, "
                    "count(DISTINCT chunk_id) c FROM graph_evidence GROUP BY edge_id) sub "
                    "WHERE sub.edge_id = e.id AND e.evidence_count <> sub.c")
    conn.commit()


def graph_state(conn) -> dict:
    return {
        "edges": conn.execute("SELECT count(*) FROM graph_edges").fetchone()[0],
        "evidence": conn.execute("SELECT count(*) FROM graph_evidence").fetchone()[0],
        "evidence_count_sum": conn.execute(
            "SELECT coalesce(sum(evidence_count),0) FROM graph_edges").fetchone()[0],
        "confidence_sum": round(conn.execute(
            "SELECT coalesce(sum(confidence),0) FROM graph_edges").fetchone()[0], 6),
    }


def bench_graph_upsert(conn) -> None:
    nodes, findings = make_findings(5_000, 20_000)
    # duplicate ~25% of findings with a new chunk (corroborating evidence across documents)
    rng = random.Random(9)
    extra = [(s, t, r, round(min(0.99, c + rng.uniform(-0.2, 0.2)), 3), e,
              str(uuid.UUID(int=rng.getrandbits(128)))) for (s, t, r, c, e, _) in
             rng.sample(findings, 5_000)]
    batch = findings + extra
    res = {"nodes": len(nodes), "findings": len(batch)}
    for name, fn in (("per_row_orm_style", upsert_per_row), ("set_based_on_conflict", upsert_set_based)):
        conn.execute(GRAPH_DDL)
        conn.commit()
        load_nodes(conn, nodes)
        first = timed(lambda: fn(conn, batch))[0]
        s1 = graph_state(conn)
        second = timed(lambda: fn(conn, batch))[0]
        s2 = graph_state(conn)
        res[name] = {"first_build_seconds": first, "rerun_seconds": second,
                     "findings_per_sec": len(batch) / first, "state_after_build": s1,
                     "rerun_is_noop": s1 == s2}
    res["same_final_state_both_methods"] = (res["per_row_orm_style"]["state_after_build"]
                                            == res["set_based_on_conflict"]["state_after_build"])
    res["speedup_set_based_x"] = (res["per_row_orm_style"]["first_build_seconds"]
                                  / res["set_based_on_conflict"]["first_build_seconds"])
    RESULTS["graph_upsert"] = res
    print("graph_upsert", json.dumps(res, indent=1, default=float))


# ---------------------------------------------------------------- 5. traversal
PROJECT_CTE = """
WITH RECURSIVE traversal(node_id, depth, path) AS (
    SELECT CAST(%(start)s AS uuid), 0, ARRAY[CAST(%(start)s AS uuid)]
    UNION ALL
    SELECT o.other_id, t.depth + 1, t.path || o.other_id
    FROM traversal t
    JOIN graph_edges e
        ON (e.source_node_id = t.node_id OR e.target_node_id = t.node_id)
    CROSS JOIN LATERAL (
        SELECT CASE WHEN e.source_node_id = t.node_id
            THEN e.target_node_id ELSE e.source_node_id END AS other_id
    ) o
    WHERE t.depth < %(depth)s AND NOT (o.other_id = ANY(t.path))
)
SELECT node_id, MIN(depth) AS depth FROM traversal WHERE depth > 0
GROUP BY node_id ORDER BY depth ASC
"""
PATHS_SQL = PROJECT_CTE.split("SELECT node_id, MIN")[0] + "SELECT count(*) FROM traversal"


def frontier_bfs(conn, start, depth: int) -> dict:
    """Level-by-level BFS with a visited set: one indexed query per hop,
    work proportional to edges touched, not to the number of distinct paths."""
    seen = {start: 0}
    frontier = [start]
    for d in range(1, depth + 1):
        if not frontier:
            break
        rows = conn.execute("SELECT source_node_id, target_node_id FROM graph_edges "
                            "WHERE source_node_id = ANY(%s) UNION ALL "
                            "SELECT source_node_id, target_node_id FROM graph_edges "
                            "WHERE target_node_id = ANY(%s)", (frontier, frontier)).fetchall()
        nxt = []
        fset = set(frontier)
        for s, t in rows:
            for other in ((t,) if s in fset else ()) + ((s,) if t in fset else ()):
                if other not in seen:
                    seen[other] = d
                    nxt.append(other)
        frontier = nxt
    seen.pop(start)
    return seen


def build_scale_free(conn, n: int, m: int = 2, seed: int = 5) -> None:
    rng = random.Random(seed)
    conn.execute(GRAPH_DDL)
    conn.commit()
    nodes = [f"entity:{i:06d}" for i in range(n)]
    load_nodes(conn, nodes)
    ids = [r[0] for r in conn.execute("SELECT id FROM graph_nodes ORDER BY canonical_id")]
    targets, edges = [], set()
    for i in range(n):  # preferential attachment: a few hub ports/companies, many leaves
        picks = set()
        while len(picks) < min(m, i):
            picks.add(rng.choice(targets) if targets else 0)
        for j in picks:
            edges.add((ids[i], ids[j], rng.choice(REL_TYPES)))
            targets += [i, j]
        if i < m:
            targets.append(i)
    with conn.cursor() as cur:
        with cur.copy("COPY graph_edges (source_node_id, target_node_id, relationship_type, "
                      "confidence) FROM STDIN") as cp:
            for s, t, r in edges:
                cp.write_row((s, t, r, 0.7))
    conn.execute("ANALYZE graph_edges")
    conn.commit()


def bench_traversal(conn, n_nodes: int) -> None:
    build_scale_free(conn, n_nodes)
    ids = [r[0] for r in conn.execute("SELECT id FROM graph_nodes ORDER BY canonical_id")]
    rng = random.Random(1)
    starts = rng.sample(ids[n_nodes // 2:], 5)  # typical (non-hub) entities
    res = {"nodes": n_nodes, "edges": conn.execute("SELECT count(*) FROM graph_edges").fetchone()[0],
           "start_nodes": len(starts), "by_depth": {}}
    for index_variant in ("project_indexes", "plus_target_index"):
        if index_variant == "plus_target_index":
            conn.execute("CREATE INDEX ix_graph_edges_target ON graph_edges (target_node_id)")
            conn.execute("ANALYZE graph_edges")
            conn.commit()
        for depth in (1, 2, 3, 4, 5, 6):
            cte_lat, bfs_lat, paths, reached, agree, timeouts = [], [], [], [], True, 0
            for s in starts:
                try:
                    conn.execute("SET statement_timeout = '20s'")
                    t = time.perf_counter()
                    cte = {r[0]: r[1] for r in conn.execute(PROJECT_CTE, {"start": s, "depth": depth})}
                    cte_lat.append(time.perf_counter() - t)
                    paths.append(conn.execute(PATHS_SQL, {"start": s, "depth": depth}).fetchone()[0])
                except psycopg.errors.QueryCanceled:
                    conn.rollback()
                    timeouts += 1
                    cte = None
                conn.execute("SET statement_timeout = 0")
                t = time.perf_counter()
                bfs = frontier_bfs(conn, s, depth)
                bfs_lat.append(time.perf_counter() - t)
                reached.append(len(bfs))
                if cte is not None and cte != bfs:
                    agree = False
                conn.rollback()
            res["by_depth"].setdefault(index_variant, {})[depth] = {
                "project_cte": ms(cte_lat) if cte_lat else None,
                "project_cte_timeouts_20s": timeouts,
                "paths_enumerated_mean": statistics.mean(paths) if paths else None,
                "frontier_bfs": ms(bfs_lat),
                "nodes_reached_mean": statistics.mean(reached),
                "results_identical": agree,
            }
            print(index_variant, depth, res["by_depth"][index_variant][depth])
    RESULTS["traversal"] = res


# ------------------------------------------------------------------- 6. vector
def bench_vector(conn, n: int, dim: int = 1536, n_queries: int = 50) -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    centers = rng.normal(size=(200, dim)).astype(np.float32)  # topic clusters, like real embeddings
    assign = rng.integers(0, 200, size=n)
    data = centers[assign] + 0.6 * rng.normal(size=(n, dim)).astype(np.float32)
    data /= np.linalg.norm(data, axis=1, keepdims=True)
    q_assign = rng.integers(0, 200, size=n_queries)
    queries = centers[q_assign] + 0.6 * rng.normal(size=(n_queries, dim)).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)

    conn.execute("DROP TABLE IF EXISTS embeddings")
    conn.execute(f"""CREATE TABLE embeddings (
        id bigserial PRIMARY KEY, source_type text NOT NULL, source_id varchar(256) NOT NULL,
        embedding_hash varchar(64) NOT NULL, embedding_vector vector({dim}) NOT NULL,
        CONSTRAINT uq_embeddings_source UNIQUE (source_type, source_id))""")
    conn.commit()
    vec = lambda v: "[" + ",".join(f"{x:.6f}" for x in v) + "]"  # noqa: E731
    t = time.perf_counter()
    with conn.cursor() as cur:
        with cur.copy("COPY embeddings (source_type, source_id, embedding_hash, embedding_vector) "
                      "FROM STDIN") as cp:
            for i, v in enumerate(data):
                cp.write_row(("document_chunk", f"chunk-{i}", f"{i:064x}", vec(v)))
    conn.commit()
    load_s = time.perf_counter() - t

    def topk(qv, sql_setup=""):
        with conn.cursor() as cur:
            if sql_setup:
                cur.execute(sql_setup)
            t0 = time.perf_counter()
            cur.execute("SELECT id FROM embeddings ORDER BY embedding_vector <=> %s::vector LIMIT 10",
                        (vec(qv),))
            ids = [r[0] for r in cur.fetchall()]
            dt = time.perf_counter() - t0
        conn.rollback()
        return ids, dt

    exact = [topk(q, "SET LOCAL enable_indexscan = off") for q in queries]
    conn.execute("SET maintenance_work_mem = '2GB'")
    t = time.perf_counter()
    conn.execute("CREATE INDEX ix_embeddings_vector_cosine_hnsw ON embeddings USING hnsw "
                 "(embedding_vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)")
    conn.commit()
    build_s = time.perf_counter() - t
    res = {"vectors": n, "dimension": dim, "copy_load_seconds": load_s,
           "hnsw_build_seconds": build_s,
           "hnsw_index_mb": conn.execute(
               "SELECT pg_relation_size('ix_embeddings_vector_cosine_hnsw')/1e6").fetchone()[0],
           "exact_scan": ms([d for _, d in exact]), "hnsw": {}}
    for ef in (40, 100):
        approx = [topk(q, f"SET LOCAL hnsw.ef_search = {ef}") for q in queries]
        recall = statistics.mean(len(set(a) & set(e)) / 10 for (a, _), (e, _) in zip(approx, exact))
        res["hnsw"][f"ef_search_{ef}"] = {**ms([d for _, d in approx]), "recall_at_10": recall}
    res["speedup_hnsw_ef40_vs_exact_p50_x"] = (res["exact_scan"]["p50_ms"]
                                               / res["hnsw"]["ef_search_40"]["p50_ms"])
    RESULTS["vector"] = res
    print("vector", json.dumps(res, indent=1, default=float))


# ------------------------------------------------------------ 7. incremental
def bench_incremental(chunks_path: Path) -> None:
    """EmbeddingService.content_hash logic: embed only rows whose sha256(text)
    is new or changed. Simulates three ingestion cycles over the real chunks."""
    real = [json.loads(line) for line in chunks_path.open()]
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    store: dict[str, str] = {}

    def cycle(texts: dict[str, str]) -> dict:
        todo = [k for k, v in texts.items() if store.get(k) != h(v)]
        tokens = sum(len(texts[k].split()) for k in todo)
        for k in todo:
            store[k] = h(texts[k])
        return {"chunks": len(texts), "embedded": len(todo), "skipped": len(texts) - len(todo),
                "words_sent_to_embedding_api": tokens}

    base = {f"{c['sha256']}:{c['index']}": c["text"] for c in real}
    rng = random.Random(4)
    edited = dict(base)
    for k in rng.sample(sorted(edited), max(1, len(edited) // 20)):  # 5% of chunks change
        edited[k] = edited[k] + " Revised assessment."
    res = {"initial_load": cycle(base), "rerun_unchanged": cycle(base),
           "rerun_5pct_changed": cycle(edited)}
    res["work_avoided_on_5pct_change_pct"] = 100 * res["rerun_5pct_changed"]["skipped"] / len(edited)
    RESULTS["incremental"] = res
    print("incremental", json.dumps(res, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="postgresql://postgres:bench@localhost/cmip_bench")
    ap.add_argument("--chunks", default="results/chunks.jsonl")
    ap.add_argument("--out", default="results")
    ap.add_argument("--fts-rows", type=int, default=200_000)
    ap.add_argument("--graph-nodes", type=int, default=20_000)
    ap.add_argument("--vectors", type=int, default=20_000)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    conn = psycopg.connect(args.dsn)
    existing = out / "database_summary.json"
    if existing.exists():  # sections can be run separately; keep earlier results
        RESULTS.update(json.loads(existing.read_text()))
    RESULTS["environment"] = {
        "postgres": conn.execute("SHOW server_version").fetchone()[0],
        "pgvector": conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
        .fetchone()[0]}
    steps = {
        "bulk_load": lambda: bench_bulk_load(conn),
        "idempotent_load": lambda: bench_idempotent(conn, Path(args.chunks)),
        "full_text": lambda: bench_full_text(conn, args.fts_rows),
        "graph_upsert": lambda: bench_graph_upsert(conn),
        "traversal": lambda: bench_traversal(conn, args.graph_nodes),
        "vector": lambda: bench_vector(conn, args.vectors),
        "incremental": lambda: bench_incremental(Path(args.chunks)),
    }
    for name, fn in steps.items():
        if args.only and name not in args.only:
            continue
        fn()
        (out / "database_summary.json").write_text(json.dumps(RESULTS, indent=2, default=float))


if __name__ == "__main__":
    main()
