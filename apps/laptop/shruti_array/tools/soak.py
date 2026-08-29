"""
Soak test harness for the DSP loop (P2/6).

Runs the synthetic 3-phone demo pipeline for an extended wall-clock
duration and reports:
  * Per-frame latency (mean, p50, p95, p99, max)
  * Queue growth (drops per minute)
  * Sync offset drift over time
  * Frame count processed

Designed to be the on-laptop version of the "all-night uptime"
acceptance test for the venue. A real multi-day soak test
would be the same code pointed at three real phones instead of
synthetic sources.

Usage:
  python -m shruti_array.tools.soak --duration 600  # 10 minutes
  python -m shruti_array.tools.soak --duration 60 --report-every 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import AppConfig
from ..dsp_loop import DspLoop, SyntheticPhoneSource
from ..sync.alignment import StreamAligner


@dataclass
class SoakReport:
    """Summary of a soak run."""

    duration_s: float
    frames_processed: int
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    drops_per_min: float
    mean_sync_offset_us: float = 0.0
    max_sync_offset_us: float = 0.0
    drift_us_per_min: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "duration_s": round(self.duration_s, 2),
            "frames_processed": self.frames_processed,
            "latency_ms": {
                "mean": round(self.mean_latency_ms, 3),
                "p50": round(self.p50_latency_ms, 3),
                "p95": round(self.p95_latency_ms, 3),
                "p99": round(self.p99_latency_ms, 3),
                "max": round(self.max_latency_ms, 3),
            },
            "drops_per_min": round(self.drops_per_min, 2),
            "sync_offset_us": {
                "mean": round(self.mean_sync_offset_us, 2),
                "max": round(self.max_sync_offset_us, 2),
                "drift_per_min": round(self.drift_us_per_min, 3),
            },
            "notes": self.notes,
        }


def _percentile(data: list[float], pct: float) -> float:
    """Return the `pct`-th percentile (0-100) of `data` using linear interpolation.

    Edge cases: empty data -> 0.0; single value -> that value.
    """
    if not data:
        return 0.0
    s = sorted(data)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def run_soak(
    duration_s: float = 600.0,
    n_phones: int = 3,
    report_every_s: float = 60.0,
    output_path: Path | None = None,
) -> SoakReport:
    """Run the synthetic pipeline for `duration_s` seconds and report.

    `output_path`, if set, is where the full per-frame latency
    series is written as a JSON file. The SoakReport (summary
    stats) is always printed to stdout regardless of `output_path`.
    """
    cfg = AppConfig.default()
    aligner = StreamAligner()
    for pid in range(n_phones):
        aligner.register(phone_id=pid, sample_rate_hz=cfg.audio.sample_rate_hz)
    sources = [SyntheticPhoneSource(phone_id=pid, target_position=(1.0, 0.0))
               for pid in range(n_phones)]
    loop = DspLoop(aligner, geometry=cfg.geometry)
    window_n_frames = loop.window_n_frames
    latencies_ms: list[float] = []
    sync_offsets_us: list[float] = []
    drops = 0
    last_report = time.time()
    started = time.time()

    print(f"Starting soak: duration={duration_s}s, phones={n_phones}, "
          f"report every {report_every_s}s")
    print(f"{'t (s)':>8} {'frames':>8} {'mean ms':>10} {'p95 ms':>10} "
          f"{'drops/min':>10} {'sync us':>10}")

    while time.time() - started < duration_s:
        frame_started = time.time()
        for _ in range(window_n_frames):
            for src in sources:
                pcm = src.next_frame()
                loop.buffer_pcm(src.phone_id, pcm)
        frame = loop.step()
        elapsed_ms = (time.time() - frame_started) * 1000.0
        latencies_ms.append(elapsed_ms)
        # Count frames that did not converge (localiser gave up).
        if frame is not None and frame.position_xy is None:
            drops += 1
        # Capture sync offset from the aligner view.
        # Use the absolute value of each phone's offset relative
        # to the master (phone 0 by default). The real
        # `LoopFrame` does not expose this, so we read the
        # aligner's `offset_samples` directly.
        try:
            offsets = [
                s.offset_samples for s in aligner._streams.values()
                if hasattr(s, 'offset_samples')
            ]
            if offsets:
                sync_offsets_us.append(max(offsets, key=abs))
        except AttributeError:
            pass

        now = time.time()
        if now - last_report >= report_every_s:
            t = now - started
            mean = statistics.mean(latencies_ms) if latencies_ms else 0.0
            p95 = _percentile(latencies_ms, 95)
            drops_per_min = drops * 60.0 / max(t, 1.0)
            sync_str = f"{sync_offsets_us[-1]:.1f}" if sync_offsets_us else "n/a"
            print(f"{t:8.1f} {len(latencies_ms):8d} {mean:10.3f} "
                  f"{p95:10.3f} {drops_per_min:10.2f} {sync_str:>10}")
            last_report = now

    total_s = time.time() - started
    mean_lat = statistics.mean(latencies_ms) if latencies_ms else 0.0
    p50 = _percentile(latencies_ms, 50)
    p95 = _percentile(latencies_ms, 95)
    p99 = _percentile(latencies_ms, 99)
    max_lat = max(latencies_ms) if latencies_ms else 0.0
    drops_per_min = drops * 60.0 / max(total_s, 1.0)
    mean_sync = statistics.mean(sync_offsets_us) if sync_offsets_us else 0.0
    max_sync = max(sync_offsets_us, key=abs) if sync_offsets_us else 0.0
    drift = (max_sync - sync_offsets_us[0]) * 60.0 / max(total_s, 1.0) \
        if sync_offsets_us else 0.0

    notes: list[str] = []
    if p99 > 25.0:
        notes.append(
            f"p99 frame latency {p99:.2f}ms exceeds the 20ms frame "
            f"deadline by {p99 - 20.0:.2f}ms — DSP loop cannot keep up."
        )
    if drops_per_min > 5.0:
        notes.append(
            f"Drop rate {drops_per_min:.1f}/min suggests an upstream "
            f"producer (microphone, network) is the bottleneck."
        )
    if abs(drift) > 5.0:
        notes.append(
            f"Sync offset drift {drift:.2f}us/min over {total_s:.0f}s "
            f"is non-trivial; consider a slower temperature or a "
            f"local oscillator spec review."
        )

    report = SoakReport(
        duration_s=total_s,
        frames_processed=len(latencies_ms),
        mean_latency_ms=mean_lat,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        p99_latency_ms=p99,
        max_latency_ms=max_lat,
        drops_per_min=drops_per_min,
        mean_sync_offset_us=mean_sync,
        max_sync_offset_us=max_sync,
        drift_us_per_min=drift,
        notes=notes,
    )
    if output_path is not None:
        output_path.write_text(json.dumps(report.to_dict(), indent=2))
        print(f"\nReport written to {output_path}")
    print(f"\nFinal report:\n{json.dumps(report.to_dict(), indent=2)}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Soak-test the synthetic SHRUTI DSP pipeline.")
    parser.add_argument(
        "--duration", type=float, default=600.0,
        help="Total soak duration in seconds (default 600 = 10 min).")
    parser.add_argument(
        "--phones", type=int, default=3,
        help="Number of synthetic phones (default 3).")
    parser.add_argument(
        "--report-every", type=float, default=60.0,
        help="Interval between progress lines, seconds (default 60).")
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional path to write the final JSON report.")
    args = parser.parse_args()
    run_soak(
        duration_s=args.duration,
        n_phones=args.phones,
        report_every_s=args.report_every,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
