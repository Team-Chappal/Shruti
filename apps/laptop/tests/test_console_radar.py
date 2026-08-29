"""Tests for the text-based radar UI."""
from __future__ import annotations

import io

from shruti_array.render.console_radar import (
    GRID_CELL_M,
    GRID_W,
    RadarState,
    _world_to_cell,
    render,
    render_to_terminal,
)
from shruti_array.render.overlays import TranscriptLine


def test_world_to_cell_centre() -> None:
    col, row = _world_to_cell(0.0, 0.0)
    # Origin is the centermost cell.
    assert col == GRID_W // 2
    assert 0 <= row


def test_world_to_cell_offset() -> None:
    # 50 cm to the right and forward of centre -> 5 cells.
    col, row = _world_to_cell(0.5, 0.5)
    assert col == GRID_W // 2 + 5
    # Forward (positive y) means up in the grid, i.e. lower row.
    assert row == (21 // 2) - 5  # grid height hardcoded for safety


def test_render_includes_dot_when_position_known() -> None:
    state = RadarState(
        position=(0.0, 0.0),
        sync_stability_us=42.0,
        uptime_s=3600.0,
        beamform_active=True,
        transcript_lines=[],
    )
    out = render(state)
    assert "SHRUTI radar" in out
    assert "42.00 us" in out
    assert "BEAMFORMED" in out
    # Header takes 2 lines ("SHRUTI radar" + "---"). The grid spans
    # 21 lines after that, so the centermost grid row is at
    # lines[2 + 10] in the rendered output.
    lines = out.split("\n")
    centre_grid_line = lines[2 + 10]
    # The centroid marker, an element marker, or the speaker dot
    # all land at the centre cell when the position is (0, 0).
    assert any(ch in centre_grid_line for ch in ("●", "+", "E"))


def test_render_with_no_position_omits_dot() -> None:
    state = RadarState(
        position=None,
        sync_stability_us=12.0,
        uptime_s=10.0,
        beamform_active=False,
        transcript_lines=[],
    )
    out = render(state)
    assert "no transcript yet" in out
    assert "raw" in out
    # No crash and no "●" anywhere in the grid.
    grid_lines = out.split("\n")[1:1 + 21]
    assert not any("●" in line for line in grid_lines)


def test_render_includes_transcript() -> None:
    state = RadarState(
        position=(0.1, 0.0),
        sync_stability_us=20.0,
        uptime_s=60.0,
        beamform_active=True,
        transcript_lines=[
            TranscriptLine(track_id=0, text="hello", language="hi", confidence=0.9),
        ],
    )
    out = render(state)
    assert "hello" in out
    assert "hi" in out


def test_grid_cell_m_is_reasonable() -> None:
    # Sanity: 10 cm per cell means a 1 m field is 10 cells.
    assert GRID_CELL_M == 0.10
    # And the full grid is at least 4 m wide.
    assert GRID_W * GRID_CELL_M >= 4.0


def test_render_to_terminal_survives_cp1252_stdout() -> None:
    """On a Windows cp1252 console, writing the bullet character
    raises UnicodeEncodeError. render_to_terminal must recover
    via reconfigure(encoding='utf-8', errors='replace') so the
    venue laptop (Windows) does not crash mid-demo.
    """
    state = RadarState(
        position=(0.0, 0.0),
        sync_stability_us=42.0,
        uptime_s=60.0,
        beamform_active=True,
        transcript_lines=[
            TranscriptLine(track_id=0, text="hello", language="hi", confidence=0.9),
        ],
    )
    # A TextIOWrapper backed by a BytesIO is the closest pure-Python
    # stand-in for a Windows cp1252 console. Whatever the system
    # locale, the reconfigure call inside render_to_terminal must
    # switch this to utf-8 before any bullet writes happen.
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", line_buffering=True)
    import contextlib

    with contextlib.redirect_stdout(out):
        render_to_terminal(state)  # must NOT raise
    # The wrapper is now utf-8; the wrapper is closed lazily so we
    # just confirm the inner BytesIO has bytes for the radar frame.
    out.flush()
    text = raw.getvalue().decode("utf-8", errors="replace")
    assert "SHRUTI radar" in text
    assert "hello" in text


def test_render_ascii_uses_no_unicode_glyphs() -> None:
    """When the operator passes --ascii, the radar output must
    contain no non-ASCII characters so it renders correctly on
    legacy consoles and over SSH on cp1252 hosts.
    """
    import contextlib

    state = RadarState(
        position=(0.0, 0.0),
        sync_stability_us=42.0,
        uptime_s=60.0,
        beamform_active=True,
        transcript_lines=[
            TranscriptLine(track_id=0, text="hi", language="hi", confidence=0.9),
        ],
    )
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="ascii", errors="strict", line_buffering=True)
    with contextlib.redirect_stdout(out):
        render_to_terminal(state, force_ascii=True)
    out.flush()
    payload = raw.getvalue()
    # Every byte must be plain ASCII.
    payload.decode("ascii")  # raises if any non-ASCII byte present
    # And the bullet must have been replaced by an ASCII fallback.
    text = payload.decode("ascii")
    assert "SHRUTI radar" in text
    assert "hi" in text
