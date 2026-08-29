"""Tests for the soak test harness (P2/6)."""
from __future__ import annotations

import json
from pathlib import Path

from shruti_array.tools.soak import _percentile, run_soak


def test_percentile_empty_returns_zero() -> None:
    assert _percentile([], 50.0) == 0.0


def test_percentile_single_value() -> None:
    assert _percentile([42.0], 50.0) == 42.0
    assert _percentile([42.0], 99.0) == 42.0


def test_percentile_basic() -> None:
    data = list(range(1, 101))  # 1..100
    assert _percentile(data, 50.0) == 50.5
    assert _percentile(data, 95.0) == 95.05


def test_percentile_handles_duplicates() -> None:
    data = [1.0, 2.0, 2.0, 3.0]
    # 50% of the way through 4 sorted values (1, 2, 2, 3) = index 1.5
    # = (2 + 2) / 2 = 2.0
    assert _percentile(data, 50.0) == 2.0


def test_run_soak_short_smoke(tmp_path: Path) -> None:
    """A 2-second soak must produce a SoakReport with at least 1 frame."""
    report = run_soak(duration_s=2.0, n_phones=3, report_every_s=1.0)
    assert report.duration_s >= 1.5
    assert report.frames_processed > 0
    assert report.mean_latency_ms >= 0.0
    assert report.p99_latency_ms >= report.mean_latency_ms


def test_run_soak_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "soak.json"
    report = run_soak(duration_s=1.0, n_phones=3, report_every_s=1.0, output_path=out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["frames_processed"] == report.frames_processed
    assert "latency_ms" in data
    assert "p50" in data["latency_ms"]
