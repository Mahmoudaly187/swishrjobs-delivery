.PHONY: help install samples test metrics mutation scan reports verify demo clean

help:
	@echo "make install   install runtime + dev dependencies"
	@echo "make samples   regenerate the synthetic corpus (240 labelled samples)"
	@echo "make test      run the acceptance suite (36 tests, one command)"
	@echo "make mutation  break the code 12 ways and prove the suite catches each"
	@echo "make metrics   re-measure masking recall and false-positive rate"
	@echo "make scan      dependency vulnerability scan"
	@echo "make verify    test + mutation + metrics + scan, the full gate"
	@echo "make demo      start the API on :8000 with reload"

install:
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt

samples:
	python3 scripts/generate_samples.py

test:
	python3 -m pytest -q

mutation:
	python3 scripts/mutation_proof.py --json reports/mutation_proof.json

metrics:
	python3 scripts/evaluate_masking.py --json > reports/masking_metrics.json
	python3 scripts/evaluate_masking.py

scan:
	python3 scripts/write_reports.py

reports: metrics scan

verify: test mutation reports
	@echo "gate green: 36 tests, 12/12 mutations caught, reports regenerated"

demo:
	python3 -m uvicorn pii_vault.api:app --host 0.0.0.0 --port 8000 --reload

clean:
	rm -rf .pytest_cache __pycache__ pii_vault/__pycache__ tests/__pycache__ scripts/__pycache__
