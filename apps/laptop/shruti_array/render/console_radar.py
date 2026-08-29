"""Text-based radar UI.

The demo's primary screen is a graphical radar (matplotlib or
pyqtgraph on a laptop, a Compose canvas on the phone), but a
text-based radar is the one that always works: it runs over a
plain terminal, over SSH, in CI, and on a headless server. This
is what `shruti-array run-radar` prints by default and what
the operators use to confirm "the system is alive" before the
demo starts.

The radar is intentionally simple: an ASCII grid with a dot for
the speaker, a stat line, and the latest transcript line. Update
it by calling `render(...)` with a snapshot.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

from .overlays import TranscriptLine

# Grid size: 21 columns x 11 rows. The centermost cell is the
# array centroid. Each cell is 10 cm. So the visible field is
# +/-1.0 m horizontally, +/-0.5 m vertically. Good enough for
# "is the dot near the centre?" without a screen.
GRID_W = 41
GRID_H = 21
GRID_CELL_M = 0.10  # 10 cm per cell

# ANSI colour codes (only if stdout is a TTY).
_USE_ANSI = sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""
if _USE_ANSI:
    _BOLD = "\033[1m"
    _DIM = "\033[2m"
    _RED = "\033[31m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _BLUE = "\033[34m"
    _CYAN = "\033[36m"
    _RESET = "\033[0m"
else:
    _BOLD = _DIM = _RED = _GREEN = _YELLOW = _BLUE = _CYAN = _RESET = ""

# ASCII fallback glyphs (used when --ascii is set or the stdout codec
# cannot encode the Unicode glyphs below). The fallback keeps the
# radar readable on legacy Windows cp1252 consoles and over SSH.
_GLYPH_DOT = "●"  # U+25CF
_GLYPH_DOT_ASCII = "o"
_GLYPH_PLUS = "+"
_GLYPH_ELEMENT = "E"


@dataclass
class RadarState:
    position: tuple[float, float] | None  # (x, y) in metres
    sync_stability_us: float
    uptime_s: float
    beamform_active: bool
    transcript_lines: list[TranscriptLine]


def _clear_screen() -> None:
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\033[2J\033[H")


def _move_cursor(row: int, col: int) -> None:
    if not sys.stdout.isatty():
        return
    sys.stdout.write(f"\033[{row};{col}H")


def _grid_origin() -> tuple[int, int]:
    """Return (row, col) of the centermost cell of the grid."""
    # 1-based for ANSI escapes.
    return (GRID_H // 2 + 1, GRID_W // 2 + 1)


def render(state: RadarState, *, force_ascii: bool = False) -> str:
    """Render the full text radar as a single string. Suitable for
    log lines and for terminal redraws.

    `force_ascii=True` swaps the bullet glyph for a plain `o` so the
    output is renderable on a Windows cp1252 console or any other
    non-UTF-8 stdout without raising UnicodeEncodeError.
    """
    out: list[str] = []
    out.append(_BOLD + "SHRUTI radar" + _RESET)
    out.append("-" * GRID_W)
    out.extend(_render_grid(state.position, force_ascii=force_ascii))
    out.append("-" * GRID_W)
    out.append(_render_stats_line(state))
    out.append(_render_transcript_lines(state.transcript_lines))
    return "\n".join(out)


def _ensure_utf8_stdout() -> None:
    """Reconfigure stdout to UTF-8 so non-ASCII glyphs don't crash
    on a Windows cp1252 console (the venue laptop).

    The reconfigure call is wrapped in try/except because some
    embedded stdouts (e.g. a `TextIOWrapper` over `BytesIO` in
    tests) report no reconfigure method. We also bail if the
    encoding is already UTF-8.
    """
    try:
        enc = sys.stdout.encoding
    except (AttributeError, ValueError):
        return
    if not enc or enc.lower() in ("utf-8", "utf8"):
        return
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        # If reconfigure fails (e.g. on a captured stream in a test
        # harness), the safest fallback is to keep going; the
        # --ascii glyph swap below catches the worst case.
        pass


def render_to_terminal(state: RadarState, *, force_ascii: bool = False) -> None:
    """Render to the current TTY, clearing it first if interactive.

    This is what the `run-radar` command calls on every DSP tick.
    On Windows cp1252 consoles we reconfigure stdout to UTF-8 with
    `errors='replace'` so the bullet glyph can't crash the demo.
    """
    if not force_ascii:
        _ensure_utf8_stdout()
    if sys.stdout.isatty():
        _clear_screen()
    sys.stdout.write(render(state, force_ascii=force_ascii) + "\n")
    sys.stdout.flush()


def _render_grid(
    position: tuple[float, float] | None,
    *,
    force_ascii: bool = False,
) -> list[str]:
    lines: list[str] = [""] * GRID_H
    # Mark the array elements (3-element triangle) at their
    # nominal positions. Default geometry: corners at
    # (-0.3, -0.2), (0.3, -0.2), (0, 0.4) (centroid-centered).
    elements = [(-0.30, -0.20), (0.30, -0.20), (0.0, 0.40)]
    dot_glyph = _GLYPH_DOT_ASCII if force_ascii else _GLYPH_DOT
    for ex, ey in elements:
        col, row = _world_to_cell(ex, ey)
        if 0 <= row < GRID_H and 0 <= col < GRID_W:
            line = lines[row]
            # Place marker (use E for element).
            lines[row] = _pad(line, col) + _GLYPH_ELEMENT
    # Speaker dot.
    if position is not None:
        col, row = _world_to_cell(*position)
        if 0 <= row < GRID_H and 0 <= col < GRID_W:
            line = lines[row]
            lines[row] = _pad(line, col) + _RED + dot_glyph + _RESET
    # Centroid cross-hair.
    crow, ccol = _grid_origin()
    crow -= 1  # 0-based
    ccol -= 1
    if 0 <= crow < GRID_H:
        line = lines[crow]
        lines[crow] = _pad(line, ccol) + _DIM + _GLYPH_PLUS + _RESET
    return ["".join(_visualise(line)) for line in lines]


def _pad(s: str, target: int) -> str:
    if len(s) >= target + 1:
        return s
    return s + " " * (target + 1 - len(s))


def _world_to_cell(x: float, y: float) -> tuple[int, int]:
    """Convert world (x, y) metres to (col, row) on the grid."""
    crow, ccol = _grid_origin()
    col = ccol - 1 + int(round(x / GRID_CELL_M))
    row = crow - 1 - int(round(y / GRID_CELL_M))
    return col, row


def _visualise(s: str) -> list[str]:
    """Return the string unchanged; placeholder for future ANSI
    column-aware colouring. Returns a list because callers feed the
    result into `"".join(...)` to compose multi-segment lines.
    """
    return [s]


def _render_stats_line(state: RadarState) -> str:
    beam = _GREEN + "BEAMFORMED" + _RESET if state.beamform_active else _DIM + "raw" + _RESET
    return (
        f"{_BOLD}sync{_RESET}: {state.sync_stability_us:6.2f} us    "
        f"{_BOLD}uptime{_RESET}: {state.uptime_s / 3600.0:5.2f} h    "
        f"{_BOLD}mode{_RESET}: {beam}"
    )


def _render_transcript_lines(lines: list[TranscriptLine]) -> str:
    if not lines:
        return _DIM + "[no transcript yet]" + _RESET
    # Show the latest 3 lines, newest at the bottom.
    shown = lines[-3:]
    rendered = [_CYAN + "[no transcript yet]" + _RESET]
    for line in shown:
        rendered.append(line.render())
    return "\n".join(rendered)


def make_state_from_observation(
    position_xy: tuple[float, float] | None,
    sync_stability_us: float,
    started_at_s: float,
    beamform_active: bool,
    transcript_lines: list[TranscriptLine],
) -> RadarState:
    return RadarState(
        position=position_xy,
        sync_stability_us=sync_stability_us,
        uptime_s=max(0.0, time.time() - started_at_s),
        beamform_active=beamform_active,
        transcript_lines=transcript_lines,
    )
