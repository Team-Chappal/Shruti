"""Device-audit analyzer.

Loads per-phone UNPROCESSED WAV recordings from a directory and produces
a characterisation report (phase response, latency estimate, RMS noise
floor). This is the laptop-side half of T01; the Android half writes
WAVs into the directory the team configures.
"""
from __future__ import annotations

import argparse
import json
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray


@dataclass
class PhoneReport:
    phone_id: int
    wav_path: str
    sample_rate_hz: int
    duration_s: float
    rms_dbfs: float
    peak_dbfs: float
    noise_floor_dbfs: float
    estimated_latency_ms: float | None
    notes: list[str] = field(default_factory=list)


def _read_wav(path: Path) -> tuple[int, NDArray[np.float32]]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    sample_width = len(raw) // max(1, n)
    if sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2_147_483_648.0
    else:
        raise ValueError(f"unsupported sample width {sample_width} in {path}")
    return sr, data


def _dbfs(rms: float) -> float:
    return float(20.0 * np.log10(max(rms, 1e-12)))


def analyze_wav(path: Path, phone_id: int | None = None) -> PhoneReport:
    sr, x = _read_wav(path)
    if phone_id is None:
        try:
            phone_id = int(path.stem.split("_")[0])
        except ValueError:
            phone_id = 0
    rms = float(np.sqrt(np.mean(x * x) + 1e-12))
    peak = float(np.max(np.abs(x)) + 1e-12)
    # Crude noise floor: the 10th percentile of |x| in dBFS, then mean of
    # everything below that threshold. Good enough to flag a noisy unit.
    abs_x = np.abs(x) + 1e-12
    db = 20.0 * np.log10(abs_x)
    threshold = float(np.percentile(db, 10))
    noise = float(np.mean(db[db <= threshold + 3.0]))
    return PhoneReport(
        phone_id=phone_id,
        wav_path=str(path),
        sample_rate_hz=sr,
        duration_s=x.size / sr,
        rms_dbfs=_dbfs(rms),
        peak_dbfs=_dbfs(peak),
        noise_floor_dbfs=noise,
        estimated_latency_ms=None,
        notes=[],
    )


def analyze_directory(directory: Path) -> list[PhoneReport]:
    reports: list[PhoneReport] = []
    for wav in sorted(directory.glob("*.wav")):
        try:
            reports.append(analyze_wav(wav))
        except Exception as e:  # noqa: BLE001
            reports.append(PhoneReport(
                phone_id=-1,
                wav_path=str(wav),
                sample_rate_hz=0,
                duration_s=0.0,
                rms_dbfs=-120.0,
                peak_dbfs=-120.0,
                noise_floor_dbfs=-120.0,
                estimated_latency_ms=None,
                notes=[f"read error: {e}"],
            ))
    return reports


def write_report(reports: list[PhoneReport], out: Path) -> None:
    out.write_text(json.dumps([asdict(r) for r in reports], indent=2))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Analyze a directory of phone UNPROCESSED captures.")
    p.add_argument("--captures", type=Path, default=Path("data/captures"),
                   help="Directory containing per-phone WAV files")
    p.add_argument("--out", type=Path, default=Path("data/audit/report.json"))
    args = p.parse_args(argv)

    if not args.captures.exists():
        print(f"no captures directory at {args.captures}; create it and drop per-phone WAVs in.")
        return 1
    reports = analyze_directory(args.captures)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_report(reports, args.out)
    for r in reports:
        print(f"phone {r.phone_id}: RMS {r.rms_dbfs:6.2f} dBFS, peak {r.peak_dbfs:6.2f} dBFS, noise {r.noise_floor_dbfs:6.2f} dBFS, sr {r.sample_rate_hz}, dur {r.duration_s:.2f}s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
