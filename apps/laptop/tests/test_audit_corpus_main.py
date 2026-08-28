"""Direct tests for `shruti_array.tools.audit.main` and
`shruti_array.tools.corpus.main`.

The audit CLI analyzes a directory of WAV captures; the
corpus CLI generates a synthetic suite. Both had `pragma: no
cover` on their main() functions because no test exercised
the dispatcher.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from shruti_array.tools import audit, corpus


def _write_wav(path: Path, samples: np.ndarray, sample_rate_hz: int = 48_000) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm)


def test_audit_main_missing_directory_returns_one(capsys, tmp_path: Path) -> None:
    """`audit --captures <missing>` should exit 1 and print
    a helpful message (the message is what the team tells
    the loaner-fleet operator when they forget the H0 step)."""
    rc = audit.main(["--captures", str(tmp_path / "no-such-dir")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "no captures directory" in captured.out
    assert "create it" in captured.out


def test_audit_main_uses_overridden_paths(tmp_path: Path, capsys) -> None:
    """`audit --captures X --out Y` should read from X and
    write the report to Y."""
    cap = tmp_path / "caps"
    cap.mkdir()
    sr = 48_000
    _write_wav(cap / "r.wav", np.zeros(sr, dtype=np.float32), sr)
    out = tmp_path / "r.json"
    rc = audit.main(["--captures", str(cap), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert isinstance(data, list)
    assert len(data) >= 1
    captured = capsys.readouterr()
    # The per-phone line should mention the RMS in dBFS.
    assert "RMS" in captured.out
    assert "phone" in captured.out


def test_audit_main_default_paths(tmp_path: Path, monkeypatch) -> None:
    """`audit` with no flags should use `data/captures` and
    `data/audit/report.json` under cwd. With a non-existent
    default captures dir, the exit code is 1."""
    monkeypatch.chdir(tmp_path)
    rc = audit.main([])
    assert rc == 1


def test_audit_main_creates_parent_directory(tmp_path: Path) -> None:
    """`audit --out <file in non-existent subdir>` should
    mkdir -p the parent. The captures dir is the same
    tmp_path/cap so the path is real, but the out file is
    several levels deep."""
    cap = tmp_path / "caps"
    cap.mkdir()
    _write_wav(cap / "r.wav", np.zeros(48_000, dtype=np.float32))
    out = tmp_path / "sub" / "deeper" / "r.json"
    rc = audit.main(["--captures", str(cap), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert out.parent.is_dir()


def test_corpus_main_synth_writes_scenes(tmp_path: Path, capsys) -> None:
    """`corpus synth --out X --scenes 3` should write 3 scene
    directories to X."""
    out = tmp_path / "corpus"
    rc = corpus.main(["synth", "--out", str(out), "--scenes", "3"])
    assert rc == 0
    assert (out / "scene_00").exists()
    assert (out / "scene_01").exists()
    assert (out / "scene_02").exists()
    captured = capsys.readouterr()
    assert "3 scenes" in captured.out


def test_corpus_main_synth_uses_default_scenes() -> None:
    """`corpus synth --out X` with no --scenes should use the
    argparse default of 5."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "c"
        rc = corpus.main(["synth", "--out", str(out)])
        assert rc == 0
        # The default scenes count is 5.
        for i in range(5):
            assert (out / f"scene_{i:02d}").exists(), f"scene_{i:02d} missing"


def test_corpus_main_synth_writes_meta_json() -> None:
    """Each scene directory should have a meta.json with the
    scene's parameters (azimuth, sample rate, etc.)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "c"
        corpus.main(["synth", "--out", str(out), "--scenes", "1"])
        meta = json.loads((out / "scene_00" / "meta.json").read_text())
        assert "name" in meta
        assert "target_azimuth_deg" in meta
        assert "sample_rate_hz" in meta


def test_corpus_main_unknown_subcommand_returns_one() -> None:
    """`corpus foo` should fail argparse (subparsers
    required=True, foo isn't a known choice)."""
    with pytest.raises(SystemExit) as exc:
        corpus.main(["foo"])
    assert exc.value.code != 0
