#!/usr/bin/env bash
# Full reproducible pipeline:
#   1. engine and analysis tests
#   2. bug-reintroduction check on the engine tests
#   3. the pre-specified study (order flow -> event injection -> matching
#      engine replay -> liquidity metrics -> naive-vs-realistic comparison
#      -> event-study tables and figures), written to results/
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"
WORKERS="${WORKERS:-4}"

echo "== 1/3 tests"
"$PYTHON" -m pytest tests/ -q

echo "== 2/3 engine tests catch injected bugs"
"$PYTHON" scripts/mutation_check.py

echo "== 3/3 study (20 seeds; a few minutes)"
"$PYTHON" scripts/run_study.py --workers "$WORKERS"
