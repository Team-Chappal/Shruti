"""Tests for tools.fetch_asr (T06)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI as a subprocess from the repo root.
    Adds the repo root to PYTHONPATH so the `tools` package
    (which lives at the repo root, not under apps/laptop) is
    importable. The Makefile's `make bench` does the same
    thing for the same reason — see its `PYTHONPATH=$$GITHUB_WORKSPACE`
    line in the CI workflow."""
    import os
    # __file__ is apps/laptop/tests/test_fetch_asr.py, so
    # parents[0]=tests, [1]=laptop, [2]=apps, [3]=repo root.
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)
    return subprocess.run(
        [sys.executable, "-m", "tools.fetch_asr", *args],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )


def test_fetch_asr_unknown_target_exits_nonzero() -> None:
    """A typo in --target must surface a useful error, not
    silently download something wrong."""
    p = _run("--target", "definitely-not-a-target")
    assert p.returncode != 0
    assert "invalid choice" in p.stderr or "invalid choice" in p.stdout


def test_fetch_asr_placeholder_target_indic_succeeds() -> None:
    """The Indic target is a placeholder until the team fills
    in the real URLs. The CLI must succeed and print a clear
    'fill URLs' message rather than failing."""
    p = _run(
        "--target", "indic",
        "--out", str(Path(__file__).resolve().parent / "_tmp_sherpa_indic"),
    )
    assert p.returncode == 0
    combined = p.stdout + p.stderr
    assert "placeholder" in combined
    assert "fill URLs" in combined or "re-run" in combined


def test_fetch_asr_placeholder_target_vosk_succeeds() -> None:
    """Same shape as the Indic placeholder — the Vosk Hindi
    URL is also a placeholder. The CLI must succeed and
    print the same shape of message."""
    p = _run(
        "--target", "vosk",
        "--out", str(Path(__file__).resolve().parent / "_tmp_sherpa_vosk"),
    )
    assert p.returncode == 0
    combined = p.stdout + p.stderr
    assert "placeholder" in combined


def test_fetch_asr_prints_config_block_on_success() -> None:
    """Even for the placeholder paths, the CLI prints a
    `Done. To use the model:` block with the export and the
    config-block snippet. Operators copy-paste the config
    block into config.py."""
    p = _run(
        "--target", "indic",
        "--out", str(Path(__file__).resolve().parent / "_tmp_sherpa_indic2"),
    )
    assert p.returncode == 0
    assert "Done. To use the model" in p.stdout
    assert "SHRUTI_ASR_ENGINE=sherpa" in p.stdout
