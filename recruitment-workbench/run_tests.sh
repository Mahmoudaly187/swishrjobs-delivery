#!/usr/bin/env bash
# One-command gate: acceptance suite, load test, mutation proof, regenerate reports.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import pytest" 2>/dev/null; then
  echo "installing test dependencies..."
  python3 -m pip install -q -r requirements-dev.txt
fi

echo "== acceptance suite =="
python3 -m pytest -q

echo
echo "== booking load test (50 threads, 5 slots) =="
python3 scripts/load_test_bookings.py --json reports/load_test.json

echo
echo "== mutation proof (breaks the code 12 ways; every break must be caught) =="
python3 scripts/mutation_proof.py --json reports/mutation_proof.json

echo
echo "== regenerate reports =="
python3 scripts/write_reports.py

echo
echo "gate green"
