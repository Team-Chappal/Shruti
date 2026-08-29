"""Boot-time tracking and pitch-mode selection.

T12: the "42 µs, all night" pitch line needs a persistent
uptime stamp that survives laptop restarts. We write the
process's first-run timestamp to a small file under
`data/` (gitignored) on the first `mark_boot()` call in a
given process lifetime. Subsequent restarts load it and
report the wall-clock-since-first-boot as the uptime.

PITCH_MODE is the gate set at the 17:30 GO/NO-GO sync-spike
on event day (per the battle plan A1 amendment). It defaults
to "tier_1" (3-phone + the "42 µs" quote); "tier_0" (2-phone
fallback + the sub-millisecond quote) is the alternative.
The value is set via the `SHRUTI_PITCH_MODE` env var, which
the demo runbook walks through setting at the gate.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# Default location for the boot-stamp file. Created on
# first mark_boot() and loaded on subsequent starts. Lives
# under data/ which is gitignored, so each laptop's stamp
# is local.
DEFAULT_BOOT_FILE: Path = Path("data/laptop_boot.timestamp")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def mark_boot(path: Path = DEFAULT_BOOT_FILE) -> float:
    """Stamp the current process's first-boot time.

    If the file doesn't exist, write `time.time()` to it. If
    it does exist, leave it alone (the original boot time
    wins, even after a restart). Returns the canonical
    boot time as a Unix timestamp.
    """
    _ensure_parent(path)
    if not path.exists():
        path.write_text(str(time.time()), encoding="utf-8")
    return float(path.read_text(encoding="utf-8").strip())


def first_boot_unix_s(path: Path = DEFAULT_BOOT_FILE) -> float:
    """Return the Unix timestamp of the first-ever mark_boot()
    on this laptop. If the file is missing, returns the
    current time (so the dashboard still renders something
    sensible before mark_boot() is called)."""
    if not path.exists():
        return time.time()
    return float(path.read_text(encoding="utf-8").strip())


def uptime_s(path: Path = DEFAULT_BOOT_FILE) -> float:
    """Wall-clock seconds since the first boot stamp."""
    return max(0.0, time.time() - first_boot_unix_s(path))


# Pitch mode: Tier-1 (3-phone, "42 µs" quote) or Tier-0
# (2-phone, sub-millisecond quote). Set via env var so the
# demo runbook can flip it at the 17:30 GO/NO-GO gate
# without a code change.
PITCH_MODE_TIER_1 = "tier_1"
PITCH_MODE_TIER_0 = "tier_0"
_VALID_PITCH_MODES = frozenset({PITCH_MODE_TIER_1, PITCH_MODE_TIER_0})


def pitch_mode() -> str:
    """Return the current pitch mode. Reads the
    `SHRUTI_PITCH_MODE` env var; defaults to `tier_1`.
    Unknown values are coerced to `tier_1` (so a typo at the
    gate doesn't disable the demo)."""
    raw = os.environ.get("SHRUTI_PITCH_MODE", PITCH_MODE_TIER_1).strip().lower()
    if raw not in _VALID_PITCH_MODES:
        return PITCH_MODE_TIER_1
    return raw
