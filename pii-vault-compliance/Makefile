.PHONY: help install samples test metrics reports scan demo clean

help:
	@echo "make install   install runtime + dev dependencies"
	@echo "make samples   regenerate the synthetic corpus (240 labelled samples)"
	@echo "make test      run the acceptance suite (the single command)"
	@echo "make metrics   re-measure masking recall and false-positive rate"
	@echo "make scan      dependency vulnerability scan"
	@echo "make reports   regenerate every report under reports/"
	@echo "make demo      start the API on :8000 with reload"

install:
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r requirements-dev.txt

samples:
	python3 scripts/generate_samples.py

test:
	python3 -m pytest -q

metrics:
	python3 scripts/evaluate_masking.py --json > reports/masking_metrics.json
	python3 scripts/evaluate_masking.py

scan:
	python3 -m pip_audit -r requirements.txt --progress-spinner off

reports: metrics scan

demo:
	python3 -m uvicorn pii_vault.api:app --host 0.0.0.0 --port 8000 --reload

clean:
	rm -rf .pytest_cache __pycache__ pii_vault/__pycache__ tests/__pycache__
