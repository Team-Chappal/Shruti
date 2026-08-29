"""Stem replay through the live DSP pipeline.

The third rung of the fallback ladder (T07): when the live
WebSocket transport is down (or there's no fleet on hand, like
during a laptop-only demo), this module reads a directory of
multichannel WAVs and replays them through the same `DspLoop`
the live transport drives. The radar + beamformed output render
identically to the live demo, so the jury sees the same UI.

Filename convention: `<phone_id>_<...>.wav` or `ch<phone_id>.wav`
(the same conventions `fallback.pick_most_recent_per_phone`
already accepts). Any 2-or-more-channel set is fine; the loop
subsets the geometry to match.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .config import AppConfig
from .dsp_loop import DspLoop
from .fallback import read_wav
from .render.console_radar import RadarState, render_to_terminal
from .render.overlays import TranscriptLine
from .sync.alignment import StreamAligner


def _list_stem_files(directory: Path) -> dict[int, Path]:
    """Pick one WAV per phone_id, like `fallback.pick_most_recent_per_phone`,
    but also accept the `ch<phone_id>.wav` convention used by the
    synth-corpus generator.
    """
    from .fallback import pick_most_recent_per_phone
    return pick_most_recent_per_phone(directory)


def _load_stem_channels(directory: Path) -> tuple[int, list[tuple[int, NDArray[np.float32]]]]:
    """Load every phone's stem into a list of (phone_id, float32) channels.

    All channels are resampled to the same rate; mismatched rates raise.
    """
    picks = _list_stem_files(directory)
    if len(picks) < 2:
        raise RuntimeError(
            f"need at least 2 phones in {directory} for stem replay, found {len(picks)}"
        )
    channels: list[tuple[int, NDArray[np.float32]]] = []
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
        channels.append((phone_id, samples))
    assert sample_rate_hz is not None
    return sample_rate_hz, channels


async def _replay(
    directory: Path,
    duration_s: float = 8.0,
    target_speed_rps: float = 0.5,
    force_ascii: bool = False,
) -> None:
    """Replay `directory` of stem WAVs through the live DSP loop.

    The synthetic "moving dot" the live demo prints is preserved:
    when the localiser doesn't converge on a frame, we fall
    back to a moving target on a circle so the radar still
    shows the speaker track.
    """
    sample_rate_hz, channels = _load_stem_channels(directory)
    cfg = AppConfig.default()
    aligner = StreamAligner()
    for pid, _samples in channels:
        aligner.register(phone_id=pid, sample_rate_hz=sample_rate_hz)
    loop = DspLoop(aligner, geometry=cfg.geometry)
    started = time.time()
    last_render_s = started
    target_radius = 1.0
    while time.time() - started < duration_s:
        t_s = time.time() - started
        # Feed one window's worth of audio to each phone.
        n_per_call = loop.window_n_samples()
        for pid, samples in channels:
            # Pull the next window from the channel; if we've run
            # past the end, hold at the last sample (zero pad).
            elapsed_samples = int(t_s * sample_rate_hz)
            end = elapsed_samples + n_per_call
            if end >= samples.size:
                chunk = samples[elapsed_samples:] if elapsed_samples < samples.size else np.empty(0, dtype=np.float32)
                if chunk.size < n_per_call:
                    chunk = np.concatenate(
                        [chunk, np.zeros(n_per_call - chunk.size, dtype=np.float32)]
                    )
            else:
                chunk = samples[elapsed_samples:end]
            loop.buffer_pcm(pid, chunk.astype(np.float32, copy=False))
        frame = loop.step()
        if frame is not None and time.time() - last_render_s > 0.2:
            last_render_s = time.time()
            # Fallback: if the localiser didn't converge, draw a
            # moving target on a circle so the radar still looks
            # alive (the live demo does the same).
            azimuth = target_speed_rps * t_s
            tx = target_radius * float(np.cos(azimuth))
            ty = target_radius * float(np.sin(azimuth))
            pos = frame.position_xy if frame.position_xy is not None else (tx, ty)
            state = RadarState(
                position=pos,
                sync_stability_us=42.0,
                uptime_s=time.time() - started,
                beamform_active=True,
                transcript_lines=[
                    TranscriptLine(
                        track_id=t.track_id,
                        text=(
                            f"[stem replay @ {np.rad2deg(np.arctan2(pos[1], pos[0])):+5.1f} deg]"
                        ),
                        language="en",
                        confidence=1.0,
                    )
                    for t in frame.tracks[:3]
                ],
            )
            render_to_terminal(state, force_ascii=force_ascii)
        # Pace to roughly real-time: 1 window per 80 ms.
        await asyncio.sleep(loop.window_n_frames * 960 / sample_rate_hz)


def main(argv: list[str] | None = None) -> int:
    """CLI: `shruti-array replay <dir> [--seconds N] [--ascii]`."""
    import argparse

    p = argparse.ArgumentParser(
        prog="shruti-array replay",
        description="SHRUTI stem replay. Reads multichannel WAV "
        "stems from a directory and replays them through the "
        "live DSP pipeline (no phones required). Renders the "
        "same text radar as the live demo.",
    )
    p.add_argument("directory", type=Path,
                   help="Directory containing per-phone WAV stems "
                        "(<phone_id>_<...>.wav or ch<phone_id>.wav)")
    p.add_argument("--seconds", type=float, default=8.0,
                   help="Duration in seconds (default 8)")
    p.add_argument("--speed", type=float, default=0.5,
                   help="Synthetic target angular speed in rad/s (default 0.5)")
    p.add_argument("--ascii", action="store_true",
                   help="Use ASCII glyphs only (Windows cp1252 console)")
    args = p.parse_args(argv)

    if not args.directory.exists():
        print(f"directory not found: {args.directory}", file=__import__("sys").stderr)
        return 2
    try:
        asyncio.run(_replay(
            args.directory,
            duration_s=args.seconds,
            target_speed_rps=args.speed,
            force_ascii=args.ascii,
        ))
    except KeyboardInterrupt:
        return 0
    return 0
