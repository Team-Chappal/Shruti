"""Tests for the judge-facing overlay renderer."""
from __future__ import annotations

from shruti_array.render.overlays import (
    SyncStatsOverlay,
    TranscriptLine,
    render_overlay,
)


def test_sync_overlay_shows_microseconds_and_target() -> None:
    text = SyncStatsOverlay(
        offset_samples=2.0,
        offset_stability_us=42.37,
        sample_rate_hz=48_000,
        uptime_s=5 * 3600,
    ).render()
    assert "42.37 us" in text
    assert "100 us" in text
    assert "5.00 h" in text


def test_overlay_renders_lines() -> None:
    sync = SyncStatsOverlay(0.0, 12.0, 48_000, 60.0)
    lines = [
        TranscriptLine(track_id=0, text="hello world", language="hi", confidence=0.91),
    ]
    out = render_overlay(sync, lines)
    assert "hello world" in out
    assert "(hi," in out
    assert " 91.0%" in out


def test_overlay_handles_empty_transcript() -> None:
    sync = SyncStatsOverlay(0.0, 12.0, 48_000, 60.0)
    out = render_overlay(sync, [])
    assert "waiting for speech" in out
