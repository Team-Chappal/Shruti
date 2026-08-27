"""Lightweight metrics: counters and a Prometheus-style text exposition.

This isn't a full Prometheus client (we don't want a runtime
dependency for a demo), but it gives the team a way to scrape
`/metrics` and watch the array come alive during the demo.

Counters are monotonic; gauges are point-in-time. Both are
process-local. The exposition format is the OpenMetrics text
format, which Prometheus and most dashboards understand.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Iterable


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def inc(self, name: str, value: int = 1, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] += value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._gauges[key] = value

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            counters = {self._fmt_name(k[0], k[1]): float(v) for k, v in self._counters.items()}
            gauges = {self._fmt_name(k[0], k[1]): float(v) for k, v in self._gauges.items()}
        return {"counters": counters, "gauges": gauges}

    def render(self) -> str:
        """Render in OpenMetrics text format."""
        lines: list[str] = []
        snap = self.snapshot()
        for name, value in sorted(snap["counters"].items()):
            lines.append(f"{name} {value:.0f}")
        for name, value in sorted(snap["gauges"].items()):
            lines.append(f"{name} {value:.3f}")
        return "\n".join(lines) + "\n"

    def merge(self, other: "Metrics") -> None:
        with self._lock:
            for key, value in other._counters.items():
                self._counters[key] += value
            for key, value in other._gauges.items():
                self._gauges[key] = value

    @staticmethod
    def _fmt_name(name: str, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return name
        rendered = ",".join(f'{k}="{v}"' for k, v in labels)
        return f"{name}{{{rendered}}}"


# Process-global instance. Cheap to use; not designed for cross-process
# aggregation (the laptop processor is single-process).
GLOBAL = Metrics()


# --- The metrics the rest of the codebase increments ------------------
# Names are stable: changing them is a breaking change for any
# downstream dashboard.

PACKETS_RECEIVED = "shruti_packets_received_total"
PACKETS_REJECTED = "shruti_packets_rejected_total"
PACKETS_DECODED = "shruti_packets_decoded_total"
BYTES_RECEIVED = "shruti_bytes_received_total"
CRC_FAILURES = "shruti_crc_failures_total"
DROPPED_FRAMES = "shruti_dropped_frames_total"
SYNC_OFFSET_US = "shruti_sync_offset_microseconds"
SYNC_STABILITY_US = "shruti_sync_stability_microseconds"
ACTIVE_PHONES = "shruti_active_phones"
BEAMFORM_OUTPUT_DB = "shruti_beamform_output_db"
ASR_TRANSCRIPT_LENGTH = "shruti_asr_transcript_length_chars"
REGRESSION_MVDR_SI_SDR = "shruti_regression_mvdr_si_sdr_db"
REGRESSION_DAS_SI_SDR = "shruti_regression_das_si_sdr_db"


__all__ = [
    "Metrics",
    "GLOBAL",
    "PACKETS_RECEIVED",
    "PACKETS_REJECTED",
    "PACKETS_DECODED",
    "BYTES_RECEIVED",
    "CRC_FAILURES",
    "DROPPED_FRAMES",
    "SYNC_OFFSET_US",
    "SYNC_STABILITY_US",
    "ACTIVE_PHONES",
    "BEAMFORM_OUTPUT_DB",
    "ASR_TRANSCRIPT_LENGTH",
    "REGRESSION_MVDR_SI_SDR",
    "REGRESSION_DAS_SI_SDR",
]
