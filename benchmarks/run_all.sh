#!/usr/bin/env bash
# Full benchmark run. Requires Tesseract on PATH and a Postgres 16 + pgvector database.
# Usage: DSN=postgresql://cmip:cmip_dev_password@localhost:5544/cmip_bench ./run_all.sh
set -euo pipefail
cd "$(dirname "$0")"
DSN="${DSN:-postgresql://cmip:cmip_dev_password@localhost:5544/cmip_bench}"
python gen_corpus.py --out corpus --docs 60 --pages 8 --scanned-ratio 0.1
python bench_ingestion.py --corpus corpus --backend ../backend --out results --workers 1 2
python bench_database.py --dsn "$DSN" --chunks results/chunks.jsonl --out results
python make_charts.py results
