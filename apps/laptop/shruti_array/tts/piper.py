"""Piper TTS adapter (real-engine scaffold).

The demo's default TTS is `MockTTS` in
`shruti_array.tts.__init__`. The real engine is
[Piper](https://github.com/rhasspy/piper), a fast, self-contained
neural TTS that runs on CPU and supports a wide variety of voices
including Indic languages.

This module is a scaffold. The team downloads a Piper voice
checkpoint (`.onnx` + `.onnx.json`) and sets the path; the rest of
the pipeline doesn't change because it goes through the stable
`TTS.speak` interface.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING

from . import TTS

if TYPE_CHECKING:
    pass


class PiperTTS(TTS):
    """TTS backed by a Piper subprocess.

    We shell out to the `piper` binary rather than linking its
    Python bindings, because the bindings add a heavy ONNX
    runtime that we don't need elsewhere. The trade-off is one
    process spawn per `speak` call; for a 4-minute demo with
    occasional readback that's fine.
    """

    def __init__(
        self,
        piper_bin: str | None = None,
        model: str | None = None,
        config: str | None = None,
    ) -> None:
        self.piper_bin = piper_bin or os.environ.get(
            "SHRUTI_PIPER_BIN", shutil.which("piper") or "piper",
        )
        self.model = model or os.environ.get(
            "SHRUTI_PIPER_MODEL", "data/models/piper/en_US-lessac-medium.onnx",
        )
        self.config = config or os.environ.get(
            "SHRUTI_PIPER_CONFIG", "data/models/piper/en_US-lessac-medium.onnx.json",
        )

    def speak(self, text: str, language: str = "en") -> bytes:
        if not text.strip():
            return b""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
            out_path = out.name
        try:
            cmd = [
                self.piper_bin,
                "--model", self.model,
                "--config", self.config,
                "--output_file", out_path,
            ]
            # Piper reads text from stdin.
            proc = subprocess.run(
                cmd, input=text.encode("utf-8"),
                check=False, capture_output=True, timeout=15,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"piper failed: {proc.stderr.decode('utf-8', errors='replace')}"
                )
            with open(out_path, "rb") as f:
                wav_bytes = f.read()
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass
        # Skip the 44-byte WAV header; the rest is 16-bit mono PCM at
        # the voice's native sample rate. The downstream consumer
        # plays this directly via the laptop's audio output.
        return wav_bytes[44:]
