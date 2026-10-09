"""Ingestion-pipeline benchmark: drives CMIP's OWN Phase 2 code
(PDFExtractor, TesseractOCRProvider, TableExtractor, DocumentChunker -
imported from backend/app, not reimplemented) over the synthetic corpus,
stage by stage, the same order app/worker/tasks.py::_run_pipeline uses:

    read bytes -> streaming size-guard + SHA-256 -> text extraction (native,
    OCR fallback) -> table extraction -> chunking

What it measures (data-engineering view):
  * end-to-end throughput (pages/s, MB/s) and per-stage time breakdown
  * native-text vs OCR cost per page (why OCR is a fallback, not the default)
  * OCR data quality on scanned pages vs. ground truth (word recall, numeric
    token recall - prices/quantities are what matter in commodity data)
  * chunk-size distribution against the 500/75 token config
  * determinism (re-chunking produces byte-identical output -> idempotent loads)
  * horizontal scaling: 1 vs N worker processes (ARQ scales the same way)

Usage:
  python bench_ingestion.py --corpus corpus --backend ../backend --out results
"""

import argparse
import asyncio
import hashlib
import json
import multiprocessing as mp
import os
import re
import statistics
import sys
import time
from pathlib import Path

CHUNK_SIZE, CHUNK_OVERLAP, MIN_NATIVE_CHARS = 500, 75, 20  # backend/app/core/config.py defaults
STREAM_PART = 64 * 1024
MAX_UPLOAD = 50 * 1024 * 1024


def _import_pipeline(backend: str):
    sys.path.insert(0, backend)
    from app.modules.documents.chunking.chunker import DocumentChunker
    from app.modules.documents.extraction.pdf_extractor import PDFExtractor
    from app.modules.documents.extraction.table_extractor import TableExtractor
    from app.modules.documents.ocr.base import OCRProvider, OCRResult
    from app.modules.documents.ocr.tesseract_provider import TesseractOCRProvider

    class TimedOCR(OCRProvider):
        """Wraps the project's real Tesseract provider, only adding a timer."""

        def __init__(self) -> None:
            self.inner = TesseractOCRProvider()
            self.seconds = 0.0
            self.calls = 0

        async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult:
            t = time.perf_counter()
            result = await self.inner.extract_text(image_bytes, language=language)
            self.seconds += time.perf_counter() - t
            self.calls += 1
            return result

    return DocumentChunker, PDFExtractor, TableExtractor, TimedOCR


def guarded_hash(data: bytes) -> str:
    """Same single-pass algorithm as documents/service.py::_guarded_stream:
    size cap enforced while streaming, SHA-256 fed in the same pass."""
    h, total = hashlib.sha256(), 0
    for i in range(0, len(data), STREAM_PART):
        part = data[i : i + STREAM_PART]
        total += len(part)
        if total > MAX_UPLOAD:
            raise ValueError("upload exceeds max size")
        h.update(part)
    return h.hexdigest()


_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.I)
_NUM = re.compile(r"\d+(?:\.\d+)?")


def ocr_quality(truth: str, ocr: str) -> tuple[float, float]:
    """Bag-of-words recall and numeric-token recall of OCR output vs truth."""
    t_words = [w.lower() for w in _WORD.findall(truth)]
    o_words = {w.lower() for w in _WORD.findall(ocr)}
    t_nums = _NUM.findall(truth)
    o_nums = set(_NUM.findall(ocr))
    word_recall = sum(w in o_words for w in t_words) / max(1, len(t_words))
    num_recall = sum(n in o_nums for n in t_nums) / max(1, len(t_nums))
    return word_recall, num_recall


def process_doc(args: tuple[str, str, dict]) -> dict:
    """One document through the pipeline - what one ARQ job does."""
    backend, path, meta = args
    DocumentChunker, PDFExtractor, TableExtractor, TimedOCR = _import_pipeline(backend)
    ocr = TimedOCR()
    extractor = PDFExtractor(ocr_provider=ocr, ocr_language="eng",
                             min_native_chars_per_page=MIN_NATIVE_CHARS)
    tables_x = TableExtractor()
    chunker = DocumentChunker(chunk_size_tokens=CHUNK_SIZE, chunk_overlap_tokens=CHUNK_OVERLAP)

    stages: dict[str, float] = {}
    t0 = time.perf_counter()
    data = Path(path).read_bytes()
    stages["read"] = time.perf_counter() - t0

    t = time.perf_counter()
    digest = guarded_hash(data)
    stages["hash_validate"] = time.perf_counter() - t

    t = time.perf_counter()
    result = asyncio.run(extractor.extract(data))
    stages["text_extract_total"] = time.perf_counter() - t
    stages["ocr"] = ocr.seconds
    stages["native_extract"] = stages["text_extract_total"] - ocr.seconds

    t = time.perf_counter()
    tables = tables_x.extract(data)
    stages["table_extract"] = time.perf_counter() - t

    t = time.perf_counter()
    chunks = chunker.chunk(result.pages)
    stages["chunk"] = time.perf_counter() - t
    total = time.perf_counter() - t0

    # determinism: re-chunk and compare a content hash of the output
    again = chunker.chunk(result.pages)
    sig = lambda cs: hashlib.sha256(  # noqa: E731
        "".join(f"{c.chunk_index}|{c.page_number}|{c.text}" for c in cs).encode()).hexdigest()

    quality = []
    for page in result.pages:
        truth = meta["scanned_ground_truth"].get(str(page.page_number))
        if truth is not None:
            wr, nr = ocr_quality(truth, page.text)
            quality.append({"page": page.page_number, "used_ocr": page.used_ocr,
                            "ocr_confidence": page.ocr_confidence,
                            "word_recall": wr, "numeric_recall": nr})

    return {
        "file": meta["file"], "bytes": len(data), "sha256": digest,
        "pages": len(result.pages), "ocr_pages": sum(p.used_ocr for p in result.pages),
        "native_pages": sum(not p.used_ocr for p in result.pages),
        "tables": len(tables), "tables_on_ocr_pages": 0,
        "chunks": [{"tokens": c.token_count, "page": c.page_number} for c in chunks],
        "chunk_output_sha256": sig(chunks), "rechunk_identical": sig(chunks) == sig(again),
        "language": result.metadata.language if result.metadata else None,
        "stages": stages, "total_seconds": total, "ocr_quality": quality,
        "chunk_text_sample": [c.text for c in chunks[:2]],
        "chunks_full": [{"index": c.chunk_index, "page": c.page_number, "tokens": c.token_count,
                         "text": c.text} for c in chunks],
    }


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--backend", default="../backend")
    ap.add_argument("--out", default="results")
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2])
    args = ap.parse_args()

    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # one Tesseract thread per worker: fair scaling test
    corpus = Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text())
    jobs = [(str(Path(args.backend).resolve()), str(corpus / m["file"]), m) for m in manifest]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    scaling = {}
    detail: list[dict] = []
    for n in args.workers:
        t = time.perf_counter()
        if n == 1:
            res = [process_doc(j) for j in jobs]
        else:
            with mp.get_context("spawn").Pool(n) as pool:
                res = pool.map(process_doc, jobs, chunksize=1)
        wall = time.perf_counter() - t
        pages = sum(r["pages"] for r in res)
        mb = sum(r["bytes"] for r in res) / 1e6
        scaling[n] = {"wall_seconds": wall, "pages_per_sec": pages / wall, "mb_per_sec": mb / wall,
                      "docs_per_min": len(res) / wall * 60}
        print(f"workers={n}: {wall:.1f}s  {pages / wall:.1f} pages/s  {mb / wall:.2f} MB/s")
        if n == 1:
            detail = res

    # ---- aggregate (from the single-worker run, so per-stage times are uncontended)
    stage_names = ["read", "hash_validate", "native_extract", "ocr", "table_extract", "chunk"]
    stage_totals = {s: sum(r["stages"][s] for r in detail) for s in stage_names}
    native_pages = sum(r["native_pages"] for r in detail)
    ocr_pages = sum(r["ocr_pages"] for r in detail)
    q = [x for r in detail for x in r["ocr_quality"]]
    toks = [c["tokens"] for r in detail for c in r["chunks"]]
    total_bytes = sum(r["bytes"] for r in detail)

    summary = {
        "corpus": {"documents": len(detail), "pages": native_pages + ocr_pages,
                   "native_pages": native_pages, "scanned_pages_ocrd": ocr_pages,
                   "megabytes": total_bytes / 1e6,
                   "scanned_pages_in_manifest": sum(len(m["scanned_pages"]) for m in manifest)},
        "scaling": scaling,
        "stage_seconds_total": stage_totals,
        "stage_share_pct": {s: 100 * v / sum(stage_totals.values()) for s, v in stage_totals.items()},
        "per_page_ms": {
            "native_text": 1000 * stage_totals["native_extract"] / max(1, native_pages + ocr_pages),
            "ocr": 1000 * stage_totals["ocr"] / max(1, ocr_pages),
        },
        "hash_validate_mb_per_sec": total_bytes / 1e6 / stage_totals["hash_validate"],
        "ocr_quality": {
            "pages_evaluated": len(q),
            "all_scanned_pages_routed_to_ocr": all(x["used_ocr"] for x in q),
            "word_recall_mean": statistics.mean(x["word_recall"] for x in q) if q else None,
            "numeric_recall_mean": statistics.mean(x["numeric_recall"] for x in q) if q else None,
            "numeric_recall_min": min(x["numeric_recall"] for x in q) if q else None,
            "tesseract_confidence_mean": statistics.mean(x["ocr_confidence"] for x in q) if q else None,
        },
        "tables": {"detected": sum(r["tables"] for r in detail)},
        "chunks": {
            "count": len(toks), "tokens_mean": statistics.mean(toks), "tokens_p50": pct(toks, 50),
            "tokens_p95": pct(toks, 95), "tokens_max": max(toks),
            "within_size_plus_overlap": all(t <= CHUNK_SIZE + CHUNK_OVERLAP for t in toks),
            "deterministic_rechunk": all(r["rechunk_identical"] for r in detail),
        },
        "dedup": {"unique_sha256": len({r["sha256"] for r in detail}), "documents": len(detail)},
        "language_detected": sorted({r["language"] for r in detail if r["language"]}),
    }
    (out / "ingestion_summary.json").write_text(json.dumps(summary, indent=2))
    # chunks are handed to the database benchmark (a real load, not synthetic rows)
    with (out / "chunks.jsonl").open("w") as fh:
        for r in detail:
            for c in r["chunks_full"]:
                fh.write(json.dumps({"file": r["file"], "sha256": r["sha256"], **c}) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
