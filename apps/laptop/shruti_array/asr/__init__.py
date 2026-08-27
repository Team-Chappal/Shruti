"""Automatic speech recognition interface.

The laptop processor never runs ASR itself in production — the NPU on
phone A handles it. This module is the abstraction: anything that can
turn a chunk of beamformed audio into a piece of text. The default ship
is `MockASR` (echoes back a placeholder so the rest of the pipeline has
something to display during testing); the team plugs in their
QNN-exported IndicWhisper/IndicConformer on the device.
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start_s: float
    end_s: float
    confidence: float = 1.0
    language: str = "en"


class ASR(abc.ABC):
    """Abstract base class for ASR engines."""

    @abc.abstractmethod
    def reset(self) -> None: ...

    @abc.abstractmethod
    def transcribe(
        self, samples, sample_rate_hz: int
    ) -> list[TranscriptSegment]: ...


class MockASR(ASR):
    """Deterministic ASR that pretends to hear the input.

    The mock returns a short, recognisable string so the rest of the
    pipeline can be exercised end-to-end without a real model. The exact
    text encodes the duration of the input chunk so tests can assert on
    what was 'recognised'.
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._call_count = 0

    def reset(self) -> None:
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def transcribe(self, samples, sample_rate_hz: int) -> list[TranscriptSegment]:
        self._call_count += 1
        n = len(samples)
        duration_s = n / float(sample_rate_hz) if sample_rate_hz else 0.0
        # Report the length so tests can assert on it.
        text = f"[mock-asr call={self._call_count} duration={duration_s:.3f}s samples={n}]"
        return [TranscriptSegment(
            text=text,
            start_s=0.0,
            end_s=duration_s,
            confidence=0.0,
            language=self.language,
        )]
