"""Corpus tools: generate synthetic scenes, record real scenes, list scenes.

`synth` writes a deterministic suite of multi-channel WAVs into
`data/corpus/synth/`. `record` is a stub: the team plugs in a recorder
that captures labeled room audio into `data/corpus/recorded/`.
"""
from __future__ import annotations

import argparse
import json
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..config import AppConfig
from ..harness.synthetic import two_speaker_scene


@dataclass
class Scene:
    name: str
    target_azimuth_deg: float
    interferer_azimuth_deg: float | None
    n_elements: int
    sample_rate_hz: int
    duration_s: float
    snr_db: float
    seed: int
    notes: str = ""


def _write_wav(path: Path, audio: NDArray[np.float32], sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm)


def synth_suite(
    out_dir: Path,
    n_scenes: int = 5,
    duration_s: float = 2.0,
    sample_rate_hz: int = 48_000,
    seed_base: int = 1234,
) -> list[Scene]:
    config = AppConfig.default()
    scenes: list[Scene] = []
    for i in range(n_scenes):
        az_deg = -60.0 + 120.0 * (i / max(1, n_scenes - 1))
        az = float(np.deg2rad(az_deg))
        interferer_az = float(np.deg2rad(-az_deg + 90.0))
        seed = seed_base + i
        channels, sources = two_speaker_scene(
            n_samples=int(duration_s * sample_rate_hz),
            sample_rate_hz=sample_rate_hz,
            geometry=config.geometry,
            azimuths_rad=(az, interferer_az),
            snr_db=15.0,
            seed=seed,
        )
        scene_dir = out_dir / f"scene_{i:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        for j, ch in enumerate(channels):
            _write_wav(scene_dir / f"ch{j}.wav", ch, sample_rate_hz)
        _write_wav(scene_dir / "target_clean.wav", sources[0], sample_rate_hz)
        _write_wav(scene_dir / "interferer_clean.wav", sources[1], sample_rate_hz)
        meta = Scene(
            name=f"scene_{i:02d}",
            target_azimuth_deg=az_deg,
            interferer_azimuth_deg=float(np.rad2deg(interferer_az)),
            n_elements=len(channels),
            sample_rate_hz=sample_rate_hz,
            duration_s=duration_s,
            snr_db=15.0,
            seed=seed,
        )
        scenes.append(meta)
        (scene_dir / "meta.json").write_text(json.dumps(asdict(meta), indent=2))
    return scenes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Corpus tools.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth", help="Generate a synthetic scene suite.")
    s.add_argument("--out", type=Path, default=Path("data/corpus/synth"))
    s.add_argument("--scenes", type=int, default=5)
    s.add_argument("--duration-s", type=float, default=2.0)
    args = p.parse_args(argv)
    if args.cmd == "synth":
        scenes = synth_suite(args.out, n_scenes=args.scenes, duration_s=args.duration_s)
        print(f"wrote {len(scenes)} scenes to {args.out}")
        return 0
    return 1  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
