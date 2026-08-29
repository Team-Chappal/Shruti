"""Per-frame beamformed WAV recorder (T15).

The "toggle moment" — the second the array switches from
non-coherent (D&S passthrough) to coherent (MVDR isolating the
speaker) — is the single most important asset the team can
capture on demo day. This module is the recorder: it accepts one
`LoopFrame` per `DspLoop.step()` and, on `finalise()`, writes:

    <out_dir>/<run_id>_phone<N>.wav    one mono PCM16 file per phone
    <out_dir>/<run_id>_beamformed.wav  the beamformed mono output

The recorder holds the per-phone and beamformed samples in
memory for the duration of the run, then writes them in one
shot. This is the simplest correct design for a demo asset: a
crash mid-run leaves no half-written file, the WAV header is
patched exactly once (no chunked-header bookkeeping), and the
file sizes in `ls` are honest.

A new recorder is created with `LoopRecorder(out_dir, phone_ids,
sample_rate_hz)`. The demo wires it to the live `DspLoop.step()`
result; tests wire it to synthetic frames. `record(frame)` is
idempotent on the phone-id set: phones the recorder wasn't told
about are ignored (matches the live phone-replacement ritual in
T11 / drop_phone).

Why a separate module:
  * `DspLoop` stays focused on the DSP path; recording is a
    presentation concern.
  * The recorder is testable in isolation — no asyncio, no
    WebSocket, no DspLoop required.
  * The same recorder will work for `replay` in a follow-up PR
    without re-implementing the WAV writer.
"""
from __future__ import annotations

import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:  # pragma: no cover
    from .dsp_loop import LoopFrame


def _default_run_id() -> str:
    """Stable, sortable, filesystem-safe run id.

    Format: ``toggle-YYYYMMDD-HHMMSS`` in local time. No
    colons, no spaces, no fractional seconds — all three are
    hostile on Windows shares, and the second-level granularity
    is enough for a demo-day capture.
    """
    return time.strftime("toggle-%Y%m%d-%H%M%S", time.localtime())


def _float_to_pcm16(audio: NDArray[np.float32]) -> bytes:
    """Clip a float32 in [-1, 1] to little-endian int16 bytes.

    Mirrors the helper in `tools/corpus.py` so the recorder's
    output is bit-identical to a corpus stem. Centralising the
    helper in one place would be cleaner; for now, the two
    are deliberately short and the duplication is honest.
    """
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    return pcm


def _write_mono_wav(path: Path, audio: NDArray[np.float32], sample_rate_hz: int) -> None:
    """Write a mono PCM16 WAV. Stdlib `wave`, no new deps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(_float_to_pcm16(audio))


@dataclass
class LoopRecorder:
    """Collects per-phone and beamformed audio across a DspLoop run.

    The recorder is constructed with the set of phone IDs that
    are *expected* to participate. A `record(frame)` call with
    a phone id the recorder wasn't told about is silently
    dropped — matches the live system, where a phone can join
    after recording starts and the early frames are simply
    missing.

    `finalise()` writes all WAVs. Returns the list of paths
    written, in deterministic order (phones ascending, then
    beamformed last), so callers can log or display them.
    """
    out_dir: Path
    phone_ids: list[int]
    sample_rate_hz: int
    run_id: str = field(default_factory=_default_run_id)
    # Per-phone sample accumulator. Initialised to empty float32
    # arrays; the first `record()` call extends them in place.
    _channels: dict[int, list[NDArray[np.float32]]] = field(init=False, repr=False)
    _beamformed: list[NDArray[np.float32]] = field(init=False, repr=False)
    _n_frames: int = field(init=False, default=0, repr=False)
    _finalised: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        # Sort for deterministic file ordering and dedupe so a
        # caller passing [0, 1, 0] doesn't get duplicate files.
        ids = sorted(set(self.phone_ids))
        self.phone_ids = ids
        self._channels = {pid: [] for pid in ids}
        self._beamformed = []

    @property
    def n_frames(self) -> int:
        """Number of `record()` calls so far. Useful for tests + metrics."""
        return self._n_frames

    def record(self, frame: LoopFrame) -> None:
        """Append one LoopFrame's per-phone channels + beamformed output.

        Tolerates frames whose channel list doesn't match the
        recorder's `phone_ids` exactly: phones the recorder
        doesn't know about are silently dropped (matches the
        live behaviour where a phone can join after recording
        starts), and a frame with fewer channels than expected
        is recorded for the phones that *do* have data.

        The `frame.channels` list is assumed to be in
        `aligner.all_phone_ids()` order — the same order the
        recorder was constructed with — because `DspLoop` and
        the demo both register phones in ascending id order.
        """
        if self._finalised:
            raise RuntimeError("LoopRecorder.record() called after finalise()")
        n_known = min(len(self.phone_ids), len(frame.channels))
        for i in range(n_known):
            pid = self.phone_ids[i]
            ch = frame.channels[i].astype(np.float32, copy=False)
            self._channels[pid].append(ch)
        self._beamformed.append(frame.beamformed.astype(np.float32, copy=False))
        self._n_frames += 1

    def finalise(self) -> list[Path]:
        """Write all WAVs to `out_dir`. Returns the list of paths written.

        Idempotent: a second call returns the same paths without
        re-writing. This is the property the demo relies on when
        a `KeyboardInterrupt` triggers a second `finalise()` from
        a `finally` block.
        """
        if self._finalised:
            return self._written_paths
        paths: list[Path] = []
        for pid in self.phone_ids:
            chunks = self._channels[pid]
            if chunks:
                audio = np.concatenate(chunks)
            else:
                # No frames recorded for this phone (it joined
                # late, or never). Write a one-sample silence
                # file so the file set is complete; the team can
                # grep the size to spot late joiners.
                audio = np.zeros(1, dtype=np.float32)
            path = self.out_dir / f"{self.run_id}_phone{pid}.wav"
            _write_mono_wav(path, audio, self.sample_rate_hz)
            paths.append(path)
        if self._beamformed:
            audio = np.concatenate(self._beamformed)
        else:
            audio = np.zeros(1, dtype=np.float32)
        bf_path = self.out_dir / f"{self.run_id}_beamformed.wav"
        _write_mono_wav(bf_path, audio, self.sample_rate_hz)
        paths.append(bf_path)
        self._written_paths = paths
        self._finalised = True
        return paths

    @property
    def _written_paths(self) -> list[Path]:  # noqa: D401 — tiny helper
        # Slot populated by `finalise`. Defined as a property so
        # the `init=False` field can be read after the fact
        # without a separate `__post_init__` dance.
        return getattr(self, "__written_paths", [])

    @_written_paths.setter
    def _written_paths(self, value: list[Path]) -> None:
        object.__setattr__(self, "__written_paths", value)
