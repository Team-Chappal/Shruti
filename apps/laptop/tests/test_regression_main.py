"""Direct tests for `shruti_array.harness.regression.main`.

The harness CLI writes a JSON report and prints a summary,
then exits 0 or 1 based on the MVDR vs D&S gate. These
tests pin down all four argument-parsing branches and the
gate's pass/fail behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shruti_array.harness import regression


def _write_fake_report(report_path: Path, mvdr: float, das: float) -> None:
    """Write a report JSON with the given avg SISDRs."""
    report = {
        "scenes": [
            {"name": "s0", "mvdr_sisdr_db": mvdr, "das_sisdr_db": das},
            {"name": "s1", "mvdr_sisdr_db": mvdr, "das_sisdr_db": das},
        ],
        "summary": "fake",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report))


def test_regression_main_writes_report_to_overridden_path(
    tmp_path: Path, capsys
) -> None:
    """`harness --out X --scenes 3` should write the JSON
    report to X and exit 0 when the gate passes. We use 3
    scenes and 1 second each; with 2 scenes and 0.1 s the
    synthetic corpus doesn't give MVDR enough samples for
    a meaningful covariance estimate (it can do worse than
    D&S on degenerate inputs, which the gate correctly
    catches)."""
    out = tmp_path / "r.json"
    rc = regression.main([
        "--scenes", "3",
        "--duration-s", "1.0",
        "--out", str(out),
    ])
    assert rc == 0, "expected pass; got the FAIL line on stdout"
    assert out.exists()
    # The to_json() method writes a list of scene dicts, not
    # a wrapper object. We assert on the shape.
    data = json.loads(out.read_text())
    assert isinstance(data, list)
    assert len(data) == 3
    for scene in data:
        assert "name" in scene
        assert "mvdr_sisdr_db" in scene
        assert "das_sisdr_db" in scene


def test_regression_main_uses_default_out_path(
    tmp_path: Path, monkeypatch
) -> None:
    """`harness` with no --out should write to
    `data/regression_runs/report.json` relative to the
    current working directory. The test chdir's into a
    tempdir so we don't pollute the real one."""
    monkeypatch.chdir(tmp_path)
    rc = regression.main(["--scenes", "3", "--duration-s", "1.0"])
    default = tmp_path / "data" / "regression_runs" / "report.json"
    assert rc == 0, "expected pass"
    assert default.exists()


def test_regression_main_fails_when_mvdr_below_gate(
    tmp_path: Path, monkeypatch
) -> None:
    """If the MVDR average is below the gate, `harness` should
    exit 1. We pass --require-mvdr-gain-db 100.0 (any real
    MVDR result will fail this)."""
    monkeypatch.chdir(tmp_path)
    rc = regression.main([
        "--scenes", "3",
        "--duration-s", "1.0",
        "--require-mvdr-gain-db", "100.0",
    ])
    assert rc == 1


def test_regression_main_prints_fail_message(tmp_path: Path, monkeypatch, capsys) -> None:
    """When the gate fails, the FAIL line should be printed
    with the actual improvement and the required threshold."""
    monkeypatch.chdir(tmp_path)
    rc = regression.main([
        "--scenes", "3",
        "--duration-s", "1.0",
        "--require-mvdr-gain-db", "100.0",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAIL" in captured.out
    assert "100.00" in captured.out
    assert "MVDR improvement" in captured.out


def test_regression_main_summary_printed(tmp_path: Path, monkeypatch, capsys) -> None:
    """The summary line (printed by `report.summary()`)
    should always be on stdout, regardless of pass/fail."""
    monkeypatch.chdir(tmp_path)
    regression.main(["--scenes", "3", "--duration-s", "1.0"])
    captured = capsys.readouterr()
    # The summary is the only output the report.to_json call
    # produces, plus the "FAIL" line if it fails. On a
    # passing run, only the summary shows.
    assert "scenes" in captured.out or "summary" in captured.out


def test_regression_main_creates_parent_directory(tmp_path: Path) -> None:
    """`harness --out <file>` should `mkdir -p` the parent
    if it doesn't exist (operators sometimes point --out
    into a fresh subdir)."""
    out = tmp_path / "sub" / "deeper" / "r.json"
    rc = regression.main([
        "--scenes", "3",
        "--duration-s", "1.0",
        "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    assert out.parent.is_dir()


def test_regression_main_does_not_run_when_argparse_fails() -> None:
    """Bad flags should fail argparse before any report
    is written."""
    with pytest.raises(SystemExit) as exc:
        regression.main(["--scenes", "notanumber"])
    assert exc.value.code != 0
