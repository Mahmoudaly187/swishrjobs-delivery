#!/usr/bin/env bash
# One-command gate: acceptance suite, then the mutation proof, then regenerate reports.
# Requires: python3 with the packages in requirements-dev.txt (pytest, pip-audit).
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import pytest" 2>/dev/null; then
  echo "installing test dependencies..."
  python3 -m pip install -q -r requirements.txt -r requirements-dev.txt
fi

echo "== acceptance suite =="
python3 -m pytest -q

echo
echo "== mutation proof (breaks the module 12 ways; every break must be caught) =="
python3 scripts/mutation_proof.py --json reports/mutation_proof.json

echo
echo "== regenerate measured reports =="
python3 scripts/evaluate_masking.py --json > reports/masking_metrics.json
python3 scripts/evaluate_masking.py
python3 scripts/write_reports.py

echo
echo "gate green"
