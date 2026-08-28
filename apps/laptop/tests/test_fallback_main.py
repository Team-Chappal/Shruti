"""Direct tests for `shruti_array.fallback.main`.

The fallback module has a CLI entry point with three
subcommands (ingest, next, ls). They're exercised by
`test_fallback_batch.py` indirectly (the `ingest` path) but
the dispatcher itself wasn't tested. This file pins down
each subcommand.
"""
from __future__ import annotations

import wave
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from shruti_array import fallback
from shruti_array.fallback import RUNG_BATCH_FILE, RUNG_LIVE_STREAM


def _write_wav(path: Path, samples: np.ndarray, sample_rate_hz: int = 48_000) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm)


def test_fallback_main_ingest_calls_batch_ingest(tmp_path: Path) -> None:
    """`fallback ingest --corpus X --out Y` should call
    `batch_ingest(X, Y, beamform='das')`."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    sr = 48_000
    for pid in (0, 1):
        _write_wav(corpus / f"{pid}_r.wav", np.zeros(sr, dtype=np.float32), sr)
    out = tmp_path / "out.wav"
    with mock.patch("shruti_array.fallback.batch_ingest") as m:
        rc = fallback.main([
            "ingest", "--corpus", str(corpus), "--out", str(out),
        ])
    assert rc == 0
    # batch_ingest(corpus, out, beamform='das') -- the
    # default is 'das' when --beamform is not given.
    args, _ = m.call_args
    assert args == (corpus, out)


def test_fallback_main_ingest_with_mvdr_flag(tmp_path: Path) -> None:
    """`fallback ingest --beamform mvdr` should forward the
    mvdr choice to `batch_ingest`."""
    corpus = tmp_path / "c"
    corpus.mkdir()
    out = tmp_path / "o.wav"
    with mock.patch("shruti_array.fallback.batch_ingest") as m:
        rc = fallback.main([
            "ingest", "--corpus", str(corpus), "--out", str(out),
            "--beamform", "mvdr",
        ])
    assert rc == 0
    args, kwargs = m.call_args
    assert args == (corpus, out)
    assert kwargs.get("beamform") == "mvdr"


def test_fallback_main_ingest_rejects_unknown_beamformer(tmp_path: Path) -> None:
    """`fallback ingest --beamform bogus` should fail argparse
    before reaching batch_ingest."""
    corpus = tmp_path / "c"
    corpus.mkdir()
    out = tmp_path / "o.wav"
    with pytest.raises(SystemExit) as exc:
        fallback.main([
            "ingest", "--corpus", str(corpus), "--out", str(out),
            "--beamform", "bogus",
        ])
    assert exc.value.code != 0


def test_fallback_main_next_prints_batch_file(capsys) -> None:
    """`fallback next` should print the next ladder rung
    down from the top (RUNG_LIVE_STREAM -> RUNG_BATCH_FILE)."""
    rc = fallback.main(["next"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "batch_file"
    # The constant is the same object, so the comparison is
    # by value, not by reference.
    assert captured.out.strip() == RUNG_BATCH_FILE.name
    # And it is NOT the top rung (we descended one step).
    assert captured.out.strip() != RUNG_LIVE_STREAM.name


def test_fallback_main_ls_lists_picks(capsys, tmp_path: Path) -> None:
    """`fallback ls <corpus>` should print one line per
    picked phone (phone_id<TAB>path)."""
    sr = 48_000
    for pid in (0, 2):
        _write_wav(tmp_path / f"{pid}_r.wav", np.zeros(sr, dtype=np.float32), sr)
    rc = fallback.main(["ls", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    lines = captured.out.strip().split("\n")
    # The order is sorted by phone_id, so 0 before 2.
    assert len(lines) == 2
    assert lines[0].startswith("0\t")
    assert lines[1].startswith("2\t")


def test_fallback_main_ls_missing_directory_prints_nothing(capsys, tmp_path: Path) -> None:
    """`fallback ls <nonexistent>` should exit 0 with no
    output (the directory doesn't exist; pick_most_recent
    returns {})."""
    rc = fallback.main(["ls", str(tmp_path / "nope")])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_fallback_main_missing_subcommand_exits_nonzero() -> None:
    """A bare `fallback` with no subcommand should fail argparse
    (required=True on the subparsers)."""
    with pytest.raises(SystemExit) as exc:
        fallback.main([])
    assert exc.value.code != 0


def test_fallback_main_unknown_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        fallback.main(["bogus"])
    assert exc.value.code != 0


def test_fallback_main_ingest_missing_required_args() -> None:
    """`fallback ingest` without --corpus or --out should
    fail argparse with a non-zero exit."""
    with pytest.raises(SystemExit) as exc:
        fallback.main(["ingest"])
    assert exc.value.code != 0
