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


def render(state: RadarState) -> str:
    """Render the full text radar as a single string. Suitable for
    log lines and for terminal redraws."""
    out: list[str] = []
    out.append(_BOLD + "SHRUTI radar" + _RESET)
    out.append("-" * GRID_W)
    out.extend(_render_grid(state.position))
    out.append("-" * GRID_W)
    out.append(_render_stats_line(state))
    out.append(_render_transcript_lines(state.transcript_lines))
    return "\n".join(out)


def render_to_terminal(state: RadarState) -> None:
    """Render to the current TTY, clearing it first if interactive.

    This is what the `run-radar` command calls on every DSP tick.
    """
    if sys.stdout.isatty():
        _clear_screen()
    sys.stdout.write(render(state) + "\n")
    sys.stdout.flush()


def _render_grid(position: tuple[float, float] | None) -> list[str]:
    lines: list[str] = [""] * GRID_H
    # Mark the array elements (3-element triangle) at their
    # nominal positions. Default geometry: corners at
    # (-0.3, -0.2), (0.3, -0.2), (0, 0.4) (centroid-centered).
    elements = [(-0.30, -0.20), (0.30, -0.20), (0.0, 0.40)]
    for ex, ey in elements:
        col, row = _world_to_cell(ex, ey)
        if 0 <= row < GRID_H and 0 <= col < GRID_W:
            line = lines[row]
            # Place marker (use E for element).
            lines[row] = _pad(line, col) + "E"
    # Speaker dot.
    if position is not None:
        col, row = _world_to_cell(*position)
        if 0 <= row < GRID_H and 0 <= col < GRID_W:
            line = lines[row]
            lines[row] = _pad(line, col) + _RED + "●" + _RESET
    # Centroid cross-hair.
    crow, ccol = _grid_origin()
    crow -= 1  # 0-based
    ccol -= 1
    if 0 <= crow < GRID_H:
        line = lines[crow]
        lines[crow] = _pad(line, ccol) + _DIM + "+" + _RESET
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


def _visualise(s: str) -> str:
    """Return the string unchanged; placeholder for future ANSI
    column-aware colouring."""
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
