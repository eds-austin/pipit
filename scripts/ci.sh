#!/usr/bin/env bash
# Run all quality gates: lint, format check, type check, tests.
# Usage: scripts/ci.sh            (uses .venv if present, otherwise PATH)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x .venv/bin/python ]]; then
    PY=.venv/bin/python
else
    PY=python3
fi

echo "==> ruff check";        "$PY" -m ruff check .
echo "==> ruff format check"; "$PY" -m ruff format --check .
echo "==> mypy";              "$PY" -m mypy
echo "==> pytest";            QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" "$PY" -m pytest -m "not private" "$@"
echo "==> all checks passed"
