"""Fallback ladder: graceful degradation when the array can't run live.

The three rungs, in order of preference:
  1. Live streaming over Wi-Fi Direct (the normal path).
  2. Batch file sync: each phone writes WAVs locally, the laptop
     pulls them when reachable, processes the most recent N seconds.
  3. Stem replay: the laptop-closed / "red light" recovery rung.
     A pre-recorded multichannel WAV stem is played through the
     pipeline so the demo can keep showing the radar + beamformed
     output when the live transport is gone. There is no on-phone
     beamformer; this rung ships as `shruti-array replay <dir>`
     (see `shruti_array.replay`).

This module owns the laptop-side "am I in fallback mode?" logic and
the batch-file ingest path. The phone-side "write WAV when Wi-Fi
Direct is down" is a small Android addition; see
apps/android/app/src/main/kotlin/dev/shruti/capture/FileFallbackWriter.kt.
"""
from __future__ import annotations

import logging
import wave
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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
RUNG_STEM_REPLAY = LadderRung(
    "stem_replay",
    "Laptop-closed recovery: pre-recorded multichannel stem played through the pipeline. "
    "No on-phone beamformer; this rung exists so the demo can keep showing the radar + "
    "beamformed output when the live transport is gone.",
)


def next_rung(current: LadderRung) -> LadderRung:
    """Return the next rung down the ladder, or the same one if already
    at the bottom (the bottom rung is the absolute fallback)."""
    if current is RUNG_LIVE_STREAM:
        return RUNG_BATCH_FILE
    if current is RUNG_BATCH_FILE:
        return RUNG_STEM_REPLAY
    return RUNG_STEM_REPLAY


# Back-compat alias. The pre-T13 release called this rung "red_light"
# and described it as "phone-only, 2-phone local beamformer". Neither
# of those is true — we do not ship an on-phone beamformer — so the
# rung was renamed. Any code or doc that still references the old
# name will get the same LadderRung object.
RUNG_RED_LIGHT = RUNG_STEM_REPLAY


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
    """Pick the single most recent WAV per phone_id from the batch dir.

    Supports two filename conventions:
      - '<phone_id>_<...>.wav'  (e.g. '0_chamber.wav')
      - 'ch<phone_id>.wav'     (e.g. 'ch0.wav', the synth-corpus convention)
    """
    result: dict[int, Path] = {}
    for path in list_batch_files(directory):
        stem = path.stem
        phone_id: int | None = None
        if "_" in stem:
            try:
                phone_id = int(stem.split("_", 1)[0])
            except ValueError:
                phone_id = None
        if phone_id is None and stem.startswith("ch"):
            try:
                phone_id = int(stem[2:])
            except ValueError:
                phone_id = None
        if phone_id is None:
            continue
        if phone_id not in result:
            result[phone_id] = path
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


def batch_ingest(
    directory: Path,
    out_path: Path,
    beamform: str = "das",
) -> Path:
    """Pull the most recent WAV per phone from `directory`, beamform
    them with delay-and-sum steered at the median GCC-PHAT TDOA, and
    write the result to `out_path`. Returns `out_path`.

    `beamform` selects the algorithm: 'das' (delay-and-sum, the
    default; cheapest, what the demo uses) or 'mvdr' (better isolation
    on recorded real-room audio but needs more snapshots).
    """
    from .beamform import das, mvdr
    from .config import AppConfig
    from .tdoa.gcc_phat import gcc_phat

    picks = pick_most_recent_per_phone(directory)
    if len(picks) < 2:
        raise RuntimeError(
            f"need at least 2 phones in {directory} for batch beamforming, "
            f"found {len(picks)}"
        )
    # Load all channels, aligning to the shortest so the matrix is square.
    channels: list[NDArray[np.float32]] = []
    sample_rate_hz: int | None = None
    for phone_id in sorted(picks):
        sr, samples = read_wav(picks[phone_id])
        if sample_rate_hz is None:
            sample_rate_hz = sr
        elif sr != sample_rate_hz:
            raise RuntimeError(
                f"sample rate mismatch: phone {phone_id} is {sr} Hz, "
                f"expected {sample_rate_hz} Hz"
            )
        channels.append(samples)
    n = min(c.size for c in channels)
    channels = [c[:n] for c in channels]
    assert sample_rate_hz is not None

    # Build an array geometry that matches the actual channel count.
    # The default geometry has 3 elements (the iQOO 3-phone tier-1
    # pitch mode); if we only have 2 captures (tier-0 mode), we use
    # the first two of the default. This keeps the math consistent
    # with the live DSP and means a Tier-0 run uses the same baseline
    # the on-device calibration expects.
    default_geom = AppConfig.default().geometry
    if len(channels) == len(default_geom.elements):
        geom = default_geom
    else:
        # Subset the geometry to the first len(channels) elements so
        # the beamformer's "geometry has N elements, got M channels"
        # guard doesn't trip.
        from .config import ArrayGeometry
        geom = ArrayGeometry(elements=default_geom.elements[: len(channels)])

    # Estimate the source direction from the GCC-PHAT TDOA between
    # the first two channels. With 2 phones this is the only direction
    # we can find; with 3+ we use the first pair as a starting point
    # and rely on the beamformer to focus.
    tau = float(gcc_phat(channels[0], channels[1]))
    # GCC-PHAT's tau is in samples; convert to azimuth by treating the
    # two phones as a baseline in the array geometry.
    baseline = float(
        np.linalg.norm(np.asarray(geom.element(0)) - np.asarray(geom.element(1)))
    )
    c = 343.0  # m/s, speed of sound at 20 C
    # tau / sr is the time delay; the far-field direction cosine is
    # (tau / sr) * c / baseline, clamped to [-1, 1] for arccos.
    cos_arg = float(np.clip(tau * c / (baseline * sample_rate_hz), -1.0, 1.0))
    azimuth_rad = float(np.arccos(cos_arg))
    log.info("batch beamform: %d channels, target azimuth = %.1f deg",
             len(channels), np.rad2deg(azimuth_rad))

    if beamform == "mvdr":
        out = mvdr.mvdr_beamform(channels, azimuth_rad, geom, sample_rate_hz)
    else:
        out = das.delay_and_sum(channels, azimuth_rad, geom, sample_rate_hz)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import wave
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        pcm = (np.clip(out, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        w.writeframes(pcm)
    log.info("wrote beamformed output to %s (%d samples)", out_path, n)
    return out_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point so `python -m shruti_array.fallback` works.

    Three subcommands:
      - `ingest`    run a single batch beamform over a directory
      - `next`      print the next rung down the ladder
      - `ls`        list the most recent WAV per phone in a directory
    """
    import argparse

    p = argparse.ArgumentParser(
        description="SHRUTI fallback ladder. Used when the live "
        "WebSocket stream is down; see docs/OPERATIONS.md and the "
        "fallback section of tools/rebuild/recipe.md.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Batch beamform a directory of WAVs.")
    ingest.add_argument("--corpus", type=Path, required=True,
                        help="Directory containing <phone_id>_<...>.wav files.")
    ingest.add_argument("--out", type=Path, required=True,
                        help="Output WAV path (16-bit PCM, mono).")
    ingest.add_argument("--beamform", choices=["das", "mvdr"], default="das",
                        help="Beamformer to use (default das).")

    sub.add_parser("next", help="Print the next ladder rung down from the top.")

    ls = sub.add_parser("ls", help="List the most recent WAV per phone in a directory.")
    ls.add_argument("corpus", type=Path,
                    help="Directory containing <phone_id>_<...>.wav files.")

    args = p.parse_args(argv)
    if args.cmd == "ingest":
        batch_ingest(args.corpus, args.out, beamform=args.beamform)
        return 0
    if args.cmd == "next":
        print(next_rung(RUNG_LIVE_STREAM).name)
        return 0
    if args.cmd == "ls":
        picks = pick_most_recent_per_phone(args.corpus)
        for phone_id in sorted(picks):
            print(f"{phone_id}\t{picks[phone_id]}")
        return 0
    return 1  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
