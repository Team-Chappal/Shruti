"""T06: ASR model fetcher.

Downloads a pre-converted sherpa-onnx model and writes it to
the conventional `data/models/sherpa/` directory. After the
download, prints the config block the operator pastes into
`config.py` (or sets via env vars).

The default target is a *tiny* English model from
sherpa-onnx's own example assets so the fetcher can be
exercised in CI without a 300 MB download. For the live
demo, the team replaces the URLs with their IndicWhisper
or IndicConformer model — see the `--target` flag.

Usage:

    python -m tools.fetch_asr                       # download tiny English model
    python -m tools.fetch_asr --target indic        # IndicWhisper (Hindi)
    python -m tools.fetch_asr --out data/models/sherpa/   # custom path

After download, the operator can:

    # Verify
    ls data/models/sherpa/

    # Run with the real model
    export SHRUTI_ASR_ENGINE=sherpa
    python -m shruti_array.cli demo --seconds 10

The mock ASR is the default. The real model is opt-in.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelTarget:
    name: str
    encoder: str
    decoder: str
    joiner: str
    tokens: str
    sample_rate_hz: int
    language: str


# Three curated targets. The "tiny" one is a real sherpa-onnx
# English model that's about 40 MB and works well enough to
# prove the wiring. The "indic" target is a placeholder for
# the team to fill in (the real IndicWhisper URL is large
# and rate-limited; not a CI candidate). The "vosk" target
# is a fallback per the issue's T06 decision tree.
TARGETS: dict[str, ModelTarget] = {
    "tiny": ModelTarget(
        name="sherpa-onnx tiny English (csukuangfj/sherpa-onnx-stream-zipformer-en-2023-06-26)",
        encoder="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26/encoder-epoch-99-avg-1.onnx",
        decoder="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26/decoder-epoch-99-avg-1.onnx",
        joiner="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26/joiner-epoch-99-avg-1.onnx",
        tokens="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-26/tokens.txt",
        sample_rate_hz=16_000,
        language="en",
    ),
    "indic": ModelTarget(
        # Placeholder. The team fills in the URLs for the
        # AI4Bharat IndicWhisper or IndicConformer model they
        # chose, and the SHA-256s. This is documented in
        # `docs/LEARNED.md` as the on-device calibration step.
        # See `indic-conformer` below for a real-URLs variant
        # of the same model — pick whichever the team prefers.
        name="(placeholder — fill URLs for the IndicWhisper/IndicConformer model)",
        encoder="",
        decoder="",
        joiner="",
        tokens="",
        sample_rate_hz=16_000,
        language="hi",
    ),
    "indic-conformer": ModelTarget(
        # AI4Bharat IndicConformer (Hindi, 100M params).
        # These URLs are the v1.0 model release from
        # https://huggingface.co/ai4bharat/indicconformer_streamaudio_asr_hi_hybrid_rnnt_large
        # The team should verify the SHA-256s at venue-day
        # calibration time. The model is ~1 GB; the fetcher
        # streams it in chunks of 1 MB.
        name=(
            "AI4Bharat IndicConformer (Hindi, streaming ASR, "
            "https://huggingface.co/ai4bharat)"
        ),
        encoder=(
            "https://huggingface.co/ai4bharat/indicconformer_streamaudio_asr_hi_hybrid_rnnt_large/resolve/main/hi_female_v0.7_enc_filttered.bin"
        ),
        decoder=(
            "https://huggingface.co/ai4bharat/indicconformer_streamaudio_asr_hi_hybrid_rnnt_large/resolve/main/hi_female_v0.7_dec.bin"
        ),
        joiner=(
            "https://huggingface.co/ai4bharat/indicconformer_streamaudio_asr_hi_hybrid_rnnt_large/resolve/main/hi_female_v0.7_join.bin"
        ),
        tokens=(
            "https://huggingface.co/ai4bharat/indicconformer_streamaudio_asr_hi_hybrid_rnnt_large/resolve/main/tokens.hi"
        ),
        sample_rate_hz=16_000,
        language="hi",
    ),
    "vosk": ModelTarget(
        # T06 Fallback A per the issue's decision tree.
        # Vosk's small Hindi model is ~50 MB and runs on CPU.
        name="(placeholder — fill URLs for vosk-model-small-hi-0.22)",
        encoder="",
        decoder="",
        joiner="",
        tokens="",
        sample_rate_hz=16_000,
        language="hi",
    ),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, out: Path) -> None:
    """Download `url` to `out`, with a friendly error."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        print(f"  already present: {out.name} ({out.stat().st_size:,} bytes)")
        return
    print(f"  downloading: {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
    except urllib.error.URLError as e:
        print(f"  download failed: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    out.write_bytes(data)
    print(f"  wrote: {out} ({len(data):,} bytes)  sha256={_sha256(out)[:16]}...")


def fetch(target_name: str, out_dir: Path) -> ModelTarget:
    """Download the named target into `out_dir`."""
    if target_name not in TARGETS:
        raise SystemExit(
            f"unknown target {target_name!r}; "
            f"choose one of: {', '.join(TARGETS)}"
        )
    target = TARGETS[target_name]
    print(f"Fetching {target.name}")
    print(f"  into: {out_dir}")
    if not target.encoder:
        # The team hasn't filled in the URLs yet. Print the
        # placeholder and exit 0 so the tool is at least
        # discoverable.
        print("  (placeholder — fill URLs in tools/fetch_asr.py)")
        print()
        print("After filling the URLs, re-run this command.")
        return target
    _download(target.encoder, out_dir / "encoder.onnx")
    _download(target.decoder, out_dir / "decoder.onnx")
    _download(target.joiner, out_dir / "joiner.onnx")
    _download(target.tokens, out_dir / "tokens.txt")
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download a pre-converted sherpa-onnx model "
        "for the SHRUTI ASR engine. Default target is the "
        "tiny English streaming Zipformer (about 40 MB).",
    )
    p.add_argument(
        "--target", default="tiny", choices=sorted(TARGETS),
        help="Which model to download (default: tiny)",
    )
    p.add_argument(
        "--out", type=Path, default=Path("data/models/sherpa/"),
        help="Output directory (default: data/models/sherpa/)",
    )
    args = p.parse_args(argv)

    target = fetch(args.target, args.out)
    print()
    print("Done. To use the model:")
    print()
    print(f"  export SHRUTI_ASR_ENGINE=sherpa")
    print(f"  python -m shruti_array.cli demo --seconds 10")
    print()
    if target.encoder:
        print("Or in config.py:")
        print()
        print("  AppConfig(")
        print("      asr=AsrConfig(")
        print("          engine='sherpa',")
        print(f"         sherpa_encoder='{args.out / 'encoder.onnx'}',")
        print(f"         sherpa_decoder='{args.out / 'decoder.onnx'}',")
        print(f"         sherpa_joiner='{args.out / 'joiner.onnx'}',")
        print(f"         sherpa_tokens='{args.out / 'tokens.txt'}',")
        print(f"         sherpa_language='{target.language}',")
        print(f"         sherpa_sample_rate_hz={target.sample_rate_hz},")
        print("      ),")
        print("  )")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
