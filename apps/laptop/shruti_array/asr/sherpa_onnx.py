"""sherpa-onnx ASR adapter (real-engine scaffold).

The demo's default ASR is the `MockASR` in
`shruti_array.asr.__init__`. The real engine is
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), a
self-contained speech recognition toolkit that runs offline on
CPU or GPU and supports a wide variety of model architectures
including IndicWhisper and IndicConformer.

This module is a scaffold. The team selects the Indic model
(AI4Bharat's IndicWhisper, AI4Bharat's IndicConformer, or
NVIDIA's Parakeet), downloads the ONNX checkpoint, and fills in
the `transcribe` method. The interface (`ASR.transcribe`) is
stable, so the rest of the pipeline doesn't change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import ASR, TranscriptSegment

if TYPE_CHECKING:
    pass


@dataclass
class SherpaOnnxConfig:
    """Paths to the ONNX encoder/decoder/joiner and tokens.

    Defaults point at the conventional filenames inside
    `data/models/sherpa/`. The team downloads the model and
    adjusts the paths in `config.yaml` (or via env vars).
    """
    encoder: str = os.environ.get(
        "SHRUTI_SHERPA_ENCODER", "data/models/sherpa/encoder.onnx",
    )
    decoder: str = os.environ.get(
        "SHRUTI_SHERPA_DECODER", "data/models/sherpa/decoder.onnx",
    )
    joiner: str = os.environ.get(
        "SHRUTI_SHERPA_JOINER", "data/models/sherpa/joiner.onnx",
    )
    tokens: str = os.environ.get(
        "SHRUTI_SHERPA_TOKENS", "data/models/sherpa/tokens.txt",
    )
    num_threads: int = int(os.environ.get("SHRUTI_SHERPA_THREADS", "4"))
    sample_rate_hz: int = 16_000
    language: str = os.environ.get("SHRUTI_SHERPA_LANG", "hi")


class SherpaOnnxASR(ASR):
    """ASR backed by a sherpa-onnx offline recognizer.

    The recognizer is created lazily on the first call to
    `transcribe` so that the laptop can boot and the WebSocket
    server can start before the (potentially large) ONNX model
    has finished loading.
    """

    def __init__(self, config: SherpaOnnxConfig | None = None) -> None:
        self.config = config or SherpaOnnxConfig()
        self._recognizer = None  # lazy
        self._call_count = 0

    def reset(self) -> None:
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def _ensure_recognizer(self) -> None:
        if self._recognizer is not None:
            return
        try:
            import sherpa_onnx  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "sherpa-onnx is not installed. Run "
                "`pip install sherpa-onnx` and download the "
                "ONNX checkpoint into data/models/sherpa/."
            ) from e
        # Offline recognizer (not streaming): the entire audio
        # chunk is passed in and a transcript is returned.
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=self.config.encoder,
            decoder=self.config.decoder,
            joiner=self.config.joiner,
            tokens=self.config.tokens,
            num_threads=self.config.num_threads,
            sample_rate=self.config.sample_rate_hz,
            decoding_method="greedy_search",
        )

    def transcribe(self, samples, sample_rate_hz: int) -> list[TranscriptSegment]:
        self._ensure_recognizer()
        self._call_count += 1
        if sample_rate_hz != self.config.sample_rate_hz:
            # The laptop beamformer runs at 48 kHz; sherpa-onnx
            # typically expects 16 kHz. The team fills in the
            # resampling here; for now we just refuse and let
            # the operator see the error rather than silently
            # mis-transcribing.
            raise ValueError(
                f"expected {self.config.sample_rate_hz} Hz, got {sample_rate_hz}; "
                "add a resampler in sherpa_onnx_asr.transcribe"
            )
        audio = samples.astype("float32") / 32768.0
        stream = self._recognizer.create_stream()
        stream.accept_waveform(self.config.sample_rate_hz, audio)
        self._recognizer.decode_streams([stream])
        text = stream.result.text.strip()
        return [TranscriptSegment(
            text=text,
            start_s=0.0,
            end_s=len(samples) / sample_rate_hz,
            confidence=0.0,  # sherpa-onnx exposes token-level confidences;
                             # mapping them to a single per-segment score
                             # is an exercise for the on-device team.
            language=self.config.language,
        )]
