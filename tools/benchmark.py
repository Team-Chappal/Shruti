"""Microbenchmark for the laptop DSP hot path.

Run with `python -m tools.benchmark`. Produces a small JSON
report under `data/benchmarks/` plus a human-readable summary
on stdout. The benchmark is for the laptop team's own
sanity-checking, not for the judges.

What we measure:
  - chirp cross-correlation per call
  - GCC-PHAT per window
  - delay-and-sum beamforming per call
  - MVDR beamforming per call (with sub-frame covariance)
  - packet encode + CRC per call

This is not a substitute for the regression harness. The
regression asserts *correctness*; the benchmark asserts
*latency*, so a refactor that breaks a constant factor is
caught here.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import numpy as np

from shruti_array.beamform import das, mvdr
from shruti_array.config import AppConfig
from shruti_array.harness.synthetic import two_speaker_scene
from shruti_array.protocol import frame_packet
from shruti_array.sync.chirp import generate_chirp
from shruti_array.sync.correlation import find_offset_sub_sample
from shruti_array.tdoa.gcc_phat import gcc_phat


def _bench(name: str, fn, iterations: int = 200) -> dict[str, float]:
    samples_ms: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    return {
        "name": name,
        "iterations": iterations,
        "median_ms": float(statistics.median(samples_ms)),
        "p95_ms": float(np.percentile(samples_ms, 95)),
        "max_ms": float(max(samples_ms)),
    }


def main() -> int:
    sr = 48_000
    n = sr  # 1 second
    geom = AppConfig.default().geometry
    rng = np.random.default_rng(0)
    x = rng.standard_normal(n).astype(np.float32)
    channels, _ = two_speaker_scene(
        n_samples=n, sample_rate_hz=sr, geometry=geom,
        azimuths_rad=(np.deg2rad(15.0), np.deg2rad(-45.0)),
        snr_db=20.0, seed=0,
    )
    chirp = generate_chirp()
    pcm = (rng.integers(-32768, 32767, 480, dtype=np.int16)).tobytes()
    rec = frame_packet(
        phone_id=0, sequence=1, sample_rate_hz=sr, samples=pcm, timestamp_us=0,
    )
    az = np.deg2rad(20.0)

    results = [
        _bench("chirp_cross_correlation_2s", lambda: find_offset_sub_sample(chirp, x)),
        _bench("gcc_phat_2048", lambda: gcc_phat(x[:2048], channels[0][:2048])),
        _bench("das_2s", lambda: das.delay_and_sum(channels, az, geom, sr)),
        _bench(
            "mvdr_2s_n8",
            lambda: mvdr.mvdr_beamform(
                channels, az, geom, sr, n_fft=4096, n_subframes=8,
            ),
        ),
        _bench("protocol_frame_packet", lambda: frame_packet(
            phone_id=0, sequence=1, sample_rate_hz=sr, samples=pcm, timestamp_us=0,
        )),
    ]

    out_dir = Path("data/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    out_path.write_text(json.dumps(results, indent=2))

    print(f"{'name':<32} {'median':>10} {'p95':>10} {'max':>10}")
    for r in results:
        print(
            f"{r['name']:<32} {r['median_ms']:>8.3f}ms "
            f"{r['p95_ms']:>8.3f}ms {r['max_ms']:>8.3f}ms"
        )
    print(f"\nwritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
