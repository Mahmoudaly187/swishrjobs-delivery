.PHONY: help install samples test load mutation reports verify demo clean

help:
	@echo "make install   install runtime + dev dependencies"
	@echo "make samples   regenerate the synthetic lead file (100 rows, duplicates)"
	@echo "make test      run the acceptance suite (one command, all green)"
	@echo "make load      run the 50-thread booking load test"
	@echo "make mutation  break the code 12 ways and prove the suite catches each"
	@echo "make reports   regenerate every report from the live code"
	@echo "make verify    test + load + mutation + reports, the full gate"
	@echo "make demo      start the API on :8000 with reload"

install:
	python3 -m pip install -r requirements-dev.txt

samples:
	python3 scripts/generate_leads.py

test:
	python3 -m pytest -q

load:
	python3 scripts/load_test_bookings.py --json reports/load_test.json

mutation:
	python3 scripts/mutation_proof.py --json reports/mutation_proof.json

reports:
	python3 scripts/write_reports.py

verify: test load mutation reports
	@echo "gate green"

demo:
	python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

clean:
	rm -rf .pytest_cache __pycache__ app/__pycache__ tests/__pycache__ scripts/__pycache__
