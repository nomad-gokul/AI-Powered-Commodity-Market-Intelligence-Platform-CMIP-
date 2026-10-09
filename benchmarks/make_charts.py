"""Render the benchmark charts (PNG) from results/*.json."""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # validated categorical slots 1-3

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def grid(ax, axis="x"):
    ax.grid(axis=axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def hbar(ax, labels, values, fmt, color=BLUE, log=False):
    y = range(len(labels))
    ax.barh(list(y), values, color=color, height=0.55)
    ax.set_yticks(list(y), labels)
    ax.invert_yaxis()
    if log:
        ax.set_xscale("log")
    for i, v in enumerate(values):
        ax.text(v * (1.08 if log else 1) + (0 if log else max(values) * 0.01), i, fmt(v),
                va="center", color=INK, fontsize=9)
    ax.set_xlim(right=max(values) * (6 if log else 1.22))
    grid(ax)


def main(results: Path) -> None:
    ing = json.loads((results / "ingestion_summary.json").read_text())
    db = json.loads((results / "database_summary.json").read_text())
    out = results / "charts"
    out.mkdir(exist_ok=True)

    # 1. where ingestion time goes
    names = {"ocr": "OCR (scanned pages)", "table_extract": "Table extraction",
             "native_extract": "Native text extraction", "chunk": "Chunking",
             "hash_validate": "SHA-256 + size guard", "read": "Read file"}
    share = ing["stage_share_pct"]
    order = sorted(share, key=share.get, reverse=True)
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    hbar(ax, [names[k] for k in order], [share[k] for k in order], lambda v: f"{v:.1f}%")
    c = ing["corpus"]
    ax.set_title("Where ingestion time goes")
    ax.set_xlabel(f"share of single-worker processing time  ({c['documents']} docs, "
                  f"{c['pages']} pages, {c['scanned_pages_ocrd']} scanned)")
    fig.tight_layout()
    fig.savefig(out / "1_ingestion_stage_share.png", dpi=160)

    # 2. worker scaling
    sc = ing["scaling"]
    fig, ax = plt.subplots(figsize=(7.5, 2.4))
    hbar(ax, [f"{k} worker{'s' if k != '1' else ''}" for k in sc],
         [v["pages_per_sec"] for v in sc.values()], lambda v: f"{v:.1f} pages/s")
    ax.set_title("Ingestion throughput scales with worker processes")
    ax.set_xlabel("pages per second (2-core sandbox)")
    fig.tight_layout()
    fig.savefig(out / "2_worker_scaling.png", dpi=160)

    # 3. full-text search
    ft = db["full_text"]
    sel, broad = ft["selective_identifier_queries"], ft["broad_topic_queries"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 2.8))
    hbar(axes[0], ["GIN index (project)", "No index (seq scan)", "ILIKE '%…%'"],
         [sel["gin_indexed"]["p50_ms"], sel["seq_scan_no_index"]["p50_ms"],
          sel["ilike_substring_scan"]["p50_ms"]], lambda v: f"{v:,.1f} ms", log=True)
    axes[0].set_title(f"Exact identifier lookups (~{sel['matching_rows_mean']:.0f} match)")
    axes[0].set_xlabel("p50 latency, ms (log scale)")
    hbar(axes[1], ["GIN index (project)", "No index (seq scan)"],
         [broad["gin_indexed"]["p50_ms"], broad["seq_scan_no_index"]["p50_ms"]],
         lambda v: f"{v:,.0f} ms")
    axes[1].set_title(f"Broad topics (~{broad['matching_rows_mean']:,.0f} matching rows)")
    axes[1].set_xlabel("p50 latency, ms")
    fig.suptitle(f"Full-text search over {ft['rows']:,} chunks", x=0.01, ha="left",
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "3_full_text_search.png", dpi=160)

    # 4. graph traversal p95 by depth
    tr = db["traversal"]["by_depth"]
    depths = sorted(int(d) for d in tr["project_indexes"])
    series = [
        ("Project CTE, project indexes", BLUE,
         [tr["project_indexes"][str(d)]["project_cte"]["p95_ms"] for d in depths]),
        ("Project CTE + target_node_id index", ORANGE,
         [tr["plus_target_index"][str(d)]["project_cte"]["p95_ms"] for d in depths]),
        ("Frontier BFS + target_node_id index", AQUA,
         [tr["plus_target_index"][str(d)]["frontier_bfs"]["p95_ms"] for d in depths]),
    ]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    for label, color, ys in series:
        ax.plot(depths, ys, color=color, linewidth=2, marker="o", markersize=5, label=label)
        ax.annotate(f"{ys[-1]:,.0f} ms", (depths[-1], ys[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.set_yscale("log")
    ax.set_xticks(depths)
    ax.set_xlim(0.8, depths[-1] + 0.9)
    ax.set_xlabel("traversal depth (hops)")
    ax.set_ylabel("p95 latency, ms (log)")
    ax.set_title(f"Knowledge-graph traversal ({db['traversal']['nodes']:,} nodes, "
                 f"{db['traversal']['edges']:,} edges)")
    ax.legend(frameon=False, loc="upper left")
    grid(ax, "y")
    fig.tight_layout()
    fig.savefig(out / "4_graph_traversal.png", dpi=160)

    # 5. graph upsert
    gu = db["graph_upsert"]
    fig, ax = plt.subplots(figsize=(7.5, 2.8))
    labels = ["First build", "Re-run (no-op)"]
    a = [gu["per_row_orm_style"]["first_build_seconds"], gu["per_row_orm_style"]["rerun_seconds"]]
    b = [gu["set_based_on_conflict"]["first_build_seconds"],
         gu["set_based_on_conflict"]["rerun_seconds"]]
    y = [0, 1]
    ax.barh([i - 0.17 for i in y], a, height=0.32, color=BLUE, label="Per-row lookup + insert/update")
    ax.barh([i + 0.17 for i in y], b, height=0.32, color=ORANGE, label="Set-based INSERT … ON CONFLICT")
    for i in y:
        ax.text(a[i] + 0.15, i - 0.17, f"{a[i]:.1f} s", va="center", fontsize=9)
        ax.text(b[i] + 0.15, i + 0.17, f"{b[i]:.2f} s", va="center", fontsize=9)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(right=max(a) * 1.18)
    ax.set_xlabel(f"seconds to upsert {gu['findings']:,} relationship findings")
    ax.set_title("Graph load: same final graph, ~{:.0f}x faster set-based".format(
        gu["speedup_set_based_x"]))
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=2)
    grid(ax)
    fig.set_size_inches(7.5, 3.3)
    fig.tight_layout()
    fig.savefig(out / "5_graph_upsert.png", dpi=160)

    # 6. vector search
    v = db["vector"]
    fig, ax = plt.subplots(figsize=(7.5, 2.4))
    hbar(ax, ["Exact scan", "HNSW (ef_search=40)"],
         [v["exact_scan"]["p50_ms"], v["hnsw"]["ef_search_40"]["p50_ms"]],
         lambda x: f"{x:.1f} ms", log=True)
    ax.set_title(f"Vector search, {v['vectors']:,} x {v['dimension']}-d  "
                 f"(HNSW recall@10 = {v['hnsw']['ef_search_40']['recall_at_10']:.2f})")
    ax.set_xlabel("p50 latency, ms (log scale)")
    fig.tight_layout()
    fig.savefig(out / "6_vector_search.png", dpi=160)
    print("charts ->", out)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "results"))
