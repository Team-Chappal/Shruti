SHELL := /bin/sh
PY ?= python

.PHONY: help install dev test test-fast lint type check audit corpus synth run-radar clean

help:
	@echo "SHRUTI array processor"
	@echo "  make install    Install runtime deps"
	@echo "  make dev        Install runtime + dev deps"
	@echo "  make test       Run the full test suite"
	@echo "  make test-fast  Run only fast tests (no audio devices)"
	@echo "  make lint       Ruff"
	@echo "  make type       mypy"
	@echo "  make check      lint + type + test"
	@echo "  make synth      Generate synthetic noisy-room corpus (deterministic)"
	@echo "  make audit      Run device-audit analyzer on a directory of WAVs"
	@echo "  make run-radar  Start the array processor (radar + toggle UI)"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev,ui]"

test:
	$(PY) -m pytest

test-fast:
	$(PY) -m pytest -m "not slow and not needs_audio_device"

lint:
	$(PY) -m ruff check shruti_array tests

type:
	$(PY) -m mypy shruti_array

check: lint type test-fast

synth:
	$(PY) -m shruti_array.tools.corpus synth --out data/corpus

audit:
	$(PY) -m shruti_array.tools.audit --captures data/captures

run-radar:
	$(PY) -m shruti_array.cli run-radar

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
