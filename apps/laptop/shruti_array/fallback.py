"""Fallback ladder: graceful degradation when the array can't run live.

The three rungs, in order of preference:
  1. Live streaming over Wi-Fi Direct (the normal path).
  2. Batch file sync: each phone writes WAVs locally, the laptop
     pulls them when reachable, processes the most recent N seconds.
  3. Red-light mode: phone-only, 2-phone local beamforming with
     the laptop closed.

This module owns the laptop-side "am I in fallback mode?" logic and
the batch-file ingest path. The phone-side "write WAV when Wi-Fi
Direct is down" is a small Android addition; see
apps/android/app/src/main/kotlin/dev/shruti/capture/FileFallbackWriter.kt.
"""
from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LadderRung:
    name: str
    description: str


# Order matters: the engine starts at the top and falls down on failure.
RUNG_LIVE_STREAM = LadderRung("live_stream", "WebSocket streaming over Wi-Fi Direct.")
RUNG_BATCH_FILE = LadderRung("batch_file", "WAV files pulled from each phone on demand.")
RUNG_RED_LIGHT = LadderRung("red_light", "Phone-only, 2-phone local beamformer.")


def next_rung(current: LadderRung) -> LadderRung:
    """Return the next rung down the ladder, or the same one if already
    at the bottom (the bottom rung is the absolute fallback)."""
    if current is RUNG_LIVE_STREAM:
        return RUNG_BATCH_FILE
    if current is RUNG_BATCH_FILE:
        return RUNG_RED_LIGHT
    return RUNG_RED_LIGHT


def read_wav(path: Path) -> tuple[int, NDArray[np.float32]]:
    """Read a 16-bit mono PCM WAV file. Returns (sample_rate_hz, float32 in [-1, 1])."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    sample_width = len(raw) // max(1, n)
    if sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2_147_483_648.0
    else:
        raise ValueError(f"unsupported sample width {sample_width} in {path}")
    return sr, data


def list_batch_files(directory: Path, phone_id: int | None = None) -> list[Path]:
    """List WAV files eligible for batch ingest, newest first.

    Convention: phone_id is encoded in the filename as `<phone_id>_<...>.wav`.
    """
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if phone_id is not None:
        files = [p for p in files if p.stem.split("_", 1)[0] == str(phone_id)]
    return files


def pick_most_recent_per_phone(directory: Path) -> dict[int, Path]:
    """Pick the single most recent WAV per phone_id from the batch dir."""
    result: dict[int, Path] = {}
    for path in list_batch_files(directory):
        try:
            pid = int(path.stem.split("_", 1)[0])
        except ValueError:
            continue
        if pid not in result:
            result[pid] = path
    return result


def file_drop_check(directory: Path) -> Iterable[Path]:
    """Generator that yields new files as they appear in the batch dir.

    The caller polls this in a loop; a real implementation would use
    inotify/FSEvents. The polling interval is the caller's
    responsibility.
    """
    seen: set[Path] = set()
    while True:
        current = list_batch_files(directory)
        for path in current:
            if path not in seen:
                seen.add(path)
                yield path
