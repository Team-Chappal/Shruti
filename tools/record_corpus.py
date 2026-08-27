"""Record a labelled noisy-room scene for the regression corpus.

This is a stub: the real implementation runs on the laptop (or the
master phone) during a quiet moment in a real room, captures 30+
seconds of audio with synchronized phone capture, and writes the
ground-truth scene description. The Python side just lays out the
file naming and metadata format; the actual audio capture lives on
the phone.

The convention is one directory per scene, with a fixed file
naming so the harness can pick up a real corpus alongside the
synthetic one.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import time


@dataclass
class RealScene:
    name: str
    room: str
    target_azimuth_deg: float
    interferer_azimuth_deg: float | None
    n_elements: int
    sample_rate_hz: int
    duration_s: float
    started_at_unix: float
    notes: str = ""

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "meta.json").write_text(json.dumps(asdict(self), indent=2))
        # The phone-side recorder drops per-channel WAVs in this
        # directory using the same convention as the synthetic
        # corpus: ch<index>.wav and target_clean.wav.
        (directory / "EXPECTED_FILES.txt").write_text(
            "\n".join([
                f"ch{i}.wav" for i in range(self.n_elements)
            ] + ["target_clean.wav", "interferer_clean.wav (if applicable)"]
        ))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scaffold a real-corpus scene directory.")
    p.add_argument("--out", type=Path, required=True, help="Directory for the scene")
    p.add_argument("--name", type=str, required=True)
    p.add_argument("--room", type=str, required=True)
    p.add_argument("--target-azimuth-deg", type=float, required=True)
    p.add_argument("--interferer-azimuth-deg", type=float, default=None)
    p.add_argument("--n-elements", type=int, default=3)
    p.add_argument("--sample-rate-hz", type=int, default=48_000)
    p.add_argument("--duration-s", type=float, default=30.0)
    p.add_argument("--notes", type=str, default="")
    args = p.parse_args(argv)

    scene = RealScene(
        name=args.name,
        room=args.room,
        target_azimuth_deg=args.target_azimuth_deg,
        interferer_azimuth_deg=args.interferer_azimuth_deg,
        n_elements=args.n_elements,
        sample_rate_hz=args.sample_rate_hz,
        duration_s=args.duration_s,
        started_at_unix=time(),
        notes=args.notes,
    )
    scene.write(args.out)
    print(f"scaffolded scene at {args.out}")
    print("Now run the phone-side capture to drop per-channel WAVs into that directory.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
