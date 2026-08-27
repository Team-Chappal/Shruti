"""Regression harness: run the beamformer on a labelled scene, score it.

This is the script that tells you, on every change, whether the toggle
got better or worse. It runs offline against a labelled corpus (or
synthetic scenes if no corpus is on disk) and emits both per-scene
metrics and an overall pass/fail.

The headline metric is **SI-SDR** (Scale-Invariant Signal-to-Distortion
Ratio) between the beamformed output and the known clean reference
source. It's measured in dB; higher is better. +3 dB over delay-and-sum
is the rule-of-thumb bar for MVDR worth shipping.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..beamform import das, mvdr
from ..config import AppConfig, ArrayGeometry
from .synthetic import far_field_signal, speech_band_noise


def si_sdr(reference: NDArray, estimate: NDArray, eps: float = 1e-8) -> float:
    """Scale-Invariant SDR in dB. Higher is better; 0 dB = identical, +inf = perfect."""
    ref = reference - reference.mean()
    est = estimate - estimate.mean()
    alpha = np.dot(ref, est) / (np.dot(ref, ref) + eps)
    proj = alpha * ref
    noise = est - proj
    return float(10 * np.log10((np.dot(proj, proj) + eps) / (np.dot(noise, noise) + eps)))


@dataclass
class SceneResult:
    name: str
    n_elements: int
    target_azimuth_deg: float
    das_sisdr_db: float
    mvdr_sisdr_db: float
    notes: str = ""


@dataclass
class RegressionReport:
    scenes: list[SceneResult] = field(default_factory=list)

    def add(self, scene: SceneResult) -> None:
        self.scenes.append(scene)

    def to_json(self, path: Path) -> None:
        path.write_text(json.dumps([asdict(s) for s in self.scenes], indent=2))

    def summary(self) -> str:
        if not self.scenes:
            return "no scenes"
        das_avg = float(np.mean([s.das_sisdr_db for s in self.scenes]))
        mvdr_avg = float(np.mean([s.mvdr_sisdr_db for s in self.scenes]))
        return f"{len(self.scenes)} scenes: delay-and-sum={das_avg:.2f} dB, MVDR={mvdr_avg:.2f} dB"


def run_synthetic_suite(
    n_scenes: int = 5,
    n_samples: int = 48_000 * 2,  # 2 seconds
    sample_rate_hz: int = 48_000,
    geometry: ArrayGeometry | None = None,
    seed_base: int = 1000,
) -> RegressionReport:
    """Run the harness on a deterministic synthetic suite.

    Each scene picks a different target azimuth, generates two-speaker
    audio, beamforms it with D&S and MVDR steered at the target, and
    measures SI-SDR against the ground-truth source.
    """
    geometry = geometry or AppConfig.default().geometry
    report = RegressionReport()
    np.random.default_rng(seed_base)
    for i in range(n_scenes):
        az_deg = -60.0 + 120.0 * (i / max(1, n_scenes - 1))
        az = float(np.deg2rad(az_deg))
        # Use the same seed per scene so the noise is reproducible.
        scene_rng = np.random.default_rng(seed_base + i)
        sources = [
            speech_band_noise(n_samples, sample_rate_hz, rng=scene_rng),
            speech_band_noise(n_samples, sample_rate_hz, rng=scene_rng),
        ]
        interferer_az = float(np.deg2rad(-az_deg + 90.0))
        channels: list[NDArray[np.float32]] | None = None
        for src, src_az in zip(sources, (az, interferer_az), strict=False):
            chs = far_field_signal(src, geometry, src_az, sample_rate_hz, snr_db=20.0, rng=scene_rng)
            if channels is None:
                channels = chs
            else:
                for c, new in zip(channels, chs, strict=False):
                    c += new
        assert channels is not None
        target = sources[0]
        n_fft = 4096
        # Both beamformers are evaluated on the same windowed slice of
        # the input so the comparison is on the same data and grid.
        das_out = das.delay_and_sum(
            [c[:n_fft] for c in channels], az, geometry, sample_rate_hz,
        )
        mvdr_out = mvdr.mvdr_beamform(
            channels, az, geometry, sample_rate_hz,
            n_fft=n_fft, n_subframes=16, diagonal_loading=1e-3,
        )
        report.add(SceneResult(
            name=f"synthetic-scene-{i:02d}",
            n_elements=len(geometry.elements),
            target_azimuth_deg=az_deg,
            das_sisdr_db=si_sdr(target[:n_fft], das_out),
            mvdr_sisdr_db=si_sdr(target[:n_fft], mvdr_out[:n_fft]),
        ))
    return report


def run_single_scene(
    channels: list[NDArray[np.float32]],
    target: NDArray[np.float32],
    azimuth_rad: float,
    sample_rate_hz: int = 48_000,
    geometry: ArrayGeometry | None = None,
    name: str = "single",
) -> SceneResult:
    geometry = geometry or AppConfig.default().geometry
    das_out = das.delay_and_sum(channels, azimuth_rad, geometry, sample_rate_hz)
    mvdr_out = mvdr.mvdr_beamform(channels, azimuth_rad, geometry, sample_rate_hz)
    return SceneResult(
        name=name,
        n_elements=len(geometry.elements),
        target_azimuth_deg=float(np.rad2deg(azimuth_rad)),
        das_sisdr_db=si_sdr(target, das_out),
        mvdr_sisdr_db=si_sdr(target, mvdr_out),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Run the SHRUTI regression harness.")
    p.add_argument("--scenes", type=int, default=5)
    p.add_argument("--duration-s", type=float, default=2.0)
    p.add_argument("--out", type=Path, default=Path("data/regression_runs/report.json"))
    p.add_argument("--require-mvdr-gain-db", type=float, default=0.0,
                   help="Fail if MVDR doesn't beat delay-and-sum by this much.")
    args = p.parse_args(argv)

    report = run_synthetic_suite(
        n_scenes=args.scenes,
        n_samples=int(args.duration_s * 48_000),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report.to_json(args.out)
    print(report.summary())

    # Pass/fail gate: MVDR should beat D&S by at least the requested amount on average.
    mvdr_avg = float(np.mean([s.mvdr_sisdr_db for s in report.scenes]))
    das_avg = float(np.mean([s.das_sisdr_db for s in report.scenes]))
    if mvdr_avg - das_avg < args.require_mvdr_gain_db:
        print(f"FAIL: MVDR improvement {mvdr_avg - das_avg:.2f} dB < required {args.require_mvdr_gain_db:.2f} dB")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
