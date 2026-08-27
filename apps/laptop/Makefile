SHELL := /bin/sh
PY ?= python

.PHONY: help install dev test test-fast lint type check audit corpus synth run-radar text-radar clean scaffold-scene dirty-check bench coverage

help:
	@echo "SHRUTI array processor"
	@echo "  make install        Install runtime deps"
	@echo "  make dev            Install runtime + dev deps"
	@echo "  make test           Run the full test suite"
	@echo "  make test-fast      Run only fast tests (no audio devices)"
	@echo "  make lint           Ruff"
	@echo "  make type           mypy"
	@echo "  make check          lint + type + test"
	@echo "  make synth          Generate synthetic noisy-room corpus (deterministic)"
	@echo "  make bench          Microbenchmark the DSP hot path"
	@echo "  make coverage       Run the test suite with coverage"
	@echo "  make scaffold-scene Scaffold a real-corpus scene directory"
	@echo "  make dirty-check    Refuse to rebuild on a dirty git tree"
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

text-radar:
	$(PY) -m shruti_array.cli text-radar --hz 2 --seconds 0

bench:
	cd .. && $(PY) -m tools.benchmark

coverage:
	$(PY) -m pytest --cov=shruti_array --cov-report=term-missing --cov-report=html:../htmlcov --cov-fail-under=70 --ignore=shruti_array/tts/piper.py --ignore=shruti_array/asr/sherpa_onnx.py

scaffold-scene:
	@$(PY) -m tools.record_corpus --out data/corpus/recorded/example --name example --room example --target-azimuth-deg 0 --duration-s 30 || true

dirty-check:
	$(PY) ../../tools/rebuild/dirty-check.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
