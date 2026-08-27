"""Render the judge-facing overlays: sync stats, latency, transcript.

The overlay text is plain ASCII; the demo's screen mirror shows it
in a monospace font. The actual rendering onto a canvas lives in
`ui/` (matplotlib/pyqtgraph); this module produces the strings.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SyncStatsOverlay:
    offset_samples: float
    offset_stability_us: float
    sample_rate_hz: int
    uptime_s: float

    def render(self) -> str:
        # 42-microsecond target is the credibility anchor; show it
        # with two decimal places so the live number is visible.
        us = self.offset_stability_us
        return (
            f"sync offset std: {us:6.2f} us    "
            f"target: < 100 us    "
            f"uptime: {self.uptime_s / 3600.0:5.2f} h"
        )


@dataclass(frozen=True)
class TranscriptLine:
    track_id: int
    text: str
    language: str
    confidence: float

    def render(self) -> str:
        conf = f"{self.confidence * 100:5.1f}%"
        return f"[{self.track_id}] ({self.language}, {conf}) {self.text}"


def render_overlay(
    sync: SyncStatsOverlay,
    lines: list[TranscriptLine],
) -> str:
    """Produce the full overlay text shown to the jury."""
    out = [sync.render(), "", "Transcript:"]
    if not lines:
        out.append("  [waiting for speech]")
    for line in lines:
        out.append("  " + line.render())
    return "\n".join(out)
