"""Runtime configuration constants and defaults.

Everything that changes between the hackathon venue and a home rehearsal
should live here, not be scattered through the code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class AudioConfig:
    sample_rate_hz: int = 48_000
    frame_ms: int = 20  # 48 kHz * 20 ms = 960 samples per frame
    channels: int = 1  # phones are mono; array is per-channel

    @property
    def frame_samples(self) -> int:
        return self.sample_rate_hz * self.frame_ms // 1000


@dataclass(frozen=True)
class ChirpConfig:
    """PRBS chirp used for ultrasonic clock sync.

    The chirp is played on one phone's speaker and recorded on every other
    phone's mic. Cross-correlating the reference against the recording gives
    the offset between phone clocks to a fraction of a sample.
    """
    f_low_hz: float = 17_500.0   # above the audible band on most phones
    f_high_hz: float = 22_000.0  # below the typical 24 kHz mic cutoff
    duration_ms: float = 60.0
    amplitude: float = 0.4       # headroom under clipping
    prbs_seed: int = 0xACE1

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0


@dataclass(frozen=True)
class SyncConfig:
    heartbeat_period_ms: int = 2_000
    offset_stability_target_us: float = 100.0  # <100 microseconds = good
    max_drift_ppm: float = 50.0                 # re-sync if drift exceeds this


@dataclass(frozen=True)
class BeamConfig:
    """Beamformer settings."""
    speed_of_sound_mps: float = 343.0
    # How often to recompute steering weights (ms). MVDR is more expensive
    # than delay-and-sum, so it can update less often.
    update_period_ms: int = 100


@dataclass(frozen=True)
class ArrayGeometry:
    """Positions of the array elements in metres, in the room's XY plane.

    The origin is the array's geometric centroid so that the per-element
    delays used by the beamformer sum to zero (weighted by element offset)
    for any direction — a property the tests and the steering maths both
    rely on.
    """
    elements: tuple[tuple[float, float], ...] = (
        (-0.30, -0.20),
        (0.30, -0.20),
        (0.0, 0.40),
    )

    def element(self, index: int) -> tuple[float, float]:
        return self.elements[index]

    def num_elements(self) -> int:
        return len(self.elements)


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    protocol: Literal["websocket", "udp"] = "websocket"


@dataclass(frozen=True)
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    chirp: ChirpConfig = field(default_factory=ChirpConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    beam: BeamConfig = field(default_factory=BeamConfig)
    geometry: ArrayGeometry = field(default_factory=ArrayGeometry)
    server: ServerConfig = field(default_factory=ServerConfig)
    data_dir: Path = Path("data")

    @classmethod
    def default(cls) -> "AppConfig":
        return cls()
