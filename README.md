# SHRUTI

[![Laptop tests](https://img.shields.io/badge/laptop-135_passing-brightgreen)](apps/laptop/tests/)
[![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen)](docs/LEARNED.md)
[![Protocol tests](https://img.shields.io/badge/android_protocol-11_passing-brightgreen)](apps/android/protocol/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](apps/laptop/pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

> **Three phones. One microphone. Zero mercy for noise.**

SHRUTI fuses multiple smartphones into a single phased microphone
array. Three iQOO devices, spaced a meter apart, capture audio
in sync, exchange their packets over OkHttp WebSocket on
`ws://<laptop>:8765/`, and a laptop array processor beamforms
the result into a clean, isolated transcript. The work runs
on the loaner fleet at the iQOO Hackathon 2026 — Smart
Education track — and ships as a self-contained build that
doesn't need the cloud.

See [`SHRUTI_BATTLE_PLAN.md`](./SHRUTI_BATTLE_PLAN.md) for
the original design doc and
[issue #20](https://github.com/Team-Chappal/Shruti/issues/20)
for the task list that drove the autonomous build.

## What it does

| The toggle | Sync proof | Localisation |
|-----------|-----------|--------------|
| RAW → BEAMFORMED flips the spatial filter from a flat mix to D&S or MVDR steered at the locked speaker. The room collapses. | The chirp handshake measures per-phone clock offset every 2 s. Target: < 100 µs. Demo target: 42 µs sustained. | GCC-PHAT TDOA + non-linear least-squares 2D fix. The radar dot moves. |

All four stages run locally. The audio never leaves the devices.

## Run it

```sh
git clone https://github.com/Team-Chappal/Shruti.git
cd Shruti
cd apps/laptop
python -m pip install -e ".[dev]"
make test        # 135 tests, ~3 s
make bench       # microbenchmark, writes data/benchmarks/latest.json
make demo        # end-to-end pipeline with synthetic phones
```

The `make demo` target is the killer dry-run. Three synthetic
phone sources generate 440 Hz tone PCM, the DSP loop produces
a beamformed output, and the text radar prints a moving dot to
the terminal. No real hardware required. Useful for a
hackathon-style "does it still work after I refactored?" check.

## Architecture

| Phone side (3 devices) | Laptop (array processor) |
|------------------------|--------------------------|
| UNPROCESSED capture @ 48 kHz | WebSocket ingest (size cap, rate limit) |
| Chirp beacon (master) | Chirp cross-correlation (sub-sample) |
| Heartbeat keep-alive | Stream aligner + drift |
| Foreground services (Capture, Chirp, Audit) | TDOA via GCC-PHAT |
| OkHttp WebSocket transport (ws://:8765) | 2D position via non-linear LS |
| Identity config (SharedPreferences) | Beamform (D&S or MVDR) |
| | ASR pass-through (sherpa-onnx / mock) |
| | Tracker + text-based radar |
| | Standalone /metrics HTTP server + jury dashboard |
| | Stem-replay fallback (`shruti-array replay <dir>`) |

The chirp handshake is the physics anchor. Everything downstream
relies on its sub-100-µs precision. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the engineering
reference and [docs/architecture.html](docs/architecture.html)
for the colour-coded live version.

## Why this approach

- **Three devices, one mic.** No special hardware, no cloud, no
  internet. The array is built from phones the user already owns.
- **Ultrasonic clock sync.** Standard time-sync approaches
  (NTP, PTP) don't work over Wi-Fi Direct with consumer
  Android. The chirp handshake is what the published phased-mic
  literature uses; the implementation is small and the precision
  is provable.
- **Laptop is the array processor.** Office Kit (iQOO's
  PC-suite bridge) lets the laptop sit on the Wi-Fi Direct
  group, so the heavy DSP work happens off-phone. Phones do
  capture, sync, and (on the master) ASR/TTS.
- **Localised model.** Indic ASR runs on phone A's NPU via
  QNN-exported ONNX. No cloud ASR, no per-call data egress.
  This is a privacy posture, not just a hackathon convenience.

## Numbers (latest benchmark)

| Operation                   | Median | p95  | Of latency budget |
|-----------------------------|--------|------|-------------------|
| Chirp xcorr (2 s window)     | 2.0 ms | 2.5 ms | 1% |
| GCC-PHAT (2048 samples)      | 0.08 ms | 0.09 ms | < 1% |
| Delay-and-sum (2 s audio)    | 15.4 ms | 16.5 ms | 8% |
| MVDR (2 s audio, 8 sub-frames) | 2.6 ms | 3.2 ms | 1.5% |
| Frame packet (CRC + header)  | 0.08 ms | 0.08 ms | < 1% |

End-to-end round-trip (capture → beamformed output) is well
under the 200 ms budget. Full numbers in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Test posture

- **135 laptop tests** (`apps/laptop/tests/`), all green.
  Coverage 89% (with `asr/sherpa_onnx.py` and `tts/piper.py`
  ignored — they're scaffold backends).
- **11 Android protocol tests** (`apps/android/protocol/`),
  byte-compatible with the Python reference, plus 4
  TransportClient wire-format tests and 3 WavFileWriter
  tests in the `:app` module.
- **CI** runs ruff, mypy (strict, no `|| true`), bandit, the
  full pytest suite with a 75% coverage gate, the end-to-end
  `shruti-array demo` smoke, the benchmark, and a
  `windows-latest` demo-smoke job that catches the cp1252
  console regression on every push. See
  `.github/workflows/ci.yml`.

## Repo layout

```
apps/
  laptop/                      # The array processor
    shruti_array/
      protocol.py              # Wire format + CRC-32C (Castagnoli, iSCSI vector)
      dsp_loop.py              # The pipeline: align, TDOA, beamform, track
      demo.py                  # End-to-end demo with synthetic phones
      sync/                    # Chirp gen, cross-correlation, alignment + drift
      tdoa/                    # GCC-PHAT
      beamform/                # Delay-and-sum + MVDR
      radar/                   # 2D position from pair TDOAs
      ingest/                  # WebSocket server + standalone /metrics HTTP
      harness/                 # Regression: synthetic corpus + SI-SDR report
      render/                  # Text-based radar UI + judge-facing overlays
      asr/  tts/               # ASR/TTS interfaces + sherpa-onnx/Piper scaffolds
      tools/                   # Audit + corpus generators
    tests/                     # 109 tests, all green
  android/                     # Kotlin/Gradle app (Compose UI, foreground services)
    protocol/                  # Byte-compatible Kotlin port of the wire format
    app/                       # CaptureService, ChirpService, TransportClient
docs/                          # Architecture, ops, security, troubleshooting, CLI
                               # ARCHITECTURE_DIAGRAMS.md, BENCHMARKS.md,
                               # architecture.html (live), LEARNED.md
tools/                         # rebuild recipe, demo runbook, record-corpus, benchmark
.github/workflows/             # ci (laptop + Android), release (sdist + Docker)
Dockerfile                     # Laptop processor image
```

## Device-bound work

The team's event-day tasks (not in the autonomous build; the
team does these on the loaner fleet before the pitch):

- Confirm UNPROCESSED capture is phase-coherent across the
  3 real iQOO phones; record the actual 42-µs sync number
- Run the device-audit step (T08: tap "Start 30 s audit
  recording" on each phone, pull the WAVs, run
  `shruti-audit` on the laptop)
- Choose the IndicWhisper / IndicConformer / Vosk model and
  fill the URLs into `tools/fetch_asr.py`, then run
  `python -m tools.fetch_asr --target indic`
- Plug in the Office Kit Wi-Fi Direct bridge host IP into
  the app's WS URL field on the setup screen
- At the 17:30 GO/NO-GO gate: set `SHRUTI_PITCH_MODE=tier_0`
  if the sync spike doesn't land (the dashboard reflects
  this live; the pitch wording changes accordingly)

Zero `NEEDS-DEVICE` markers remain in `apps/android/` —
all four services (Capture, Chirp, Audit) are real, the
transport is real OkHttp WebSocket, the permissions are
real, the identity is real SharedPreferences. What's left
is calibration, not code.

## Team

Team Chappal — iQOO City Battles 2026, Bengaluru.

## Docs

- [Battle plan](./SHRUTI_BATTLE_PLAN.md) — the original 7-section design doc
- [Two-week refinement](./docs/ideas/shruti-two-week-refinement.md)
- [Architecture](./docs/ARCHITECTURE.md), [HTML](./docs/architecture.html), [ASCII](./docs/ARCHITECTURE_DIAGRAMS.md)
- [Operations runbook](./docs/OPERATIONS.md)
- [Security & trust model](./docs/SECURITY.md)
- [Troubleshooting](./docs/TROUBLESHOOTING.md)
- [CLI reference](./docs/CLI.md)
- [Benchmarks](./docs/BENCHMARKS.md)
- [What we actually learned](./docs/LEARNED.md)
- [Agent config](./AGENTS.md)
- [Changelog](./CHANGELOG.md)
- [Rebuild recipe](./tools/rebuild/recipe.md)
- [Demo runbook](./tools/rebuild/demo-runbook.md)
- [Submission assets](./docs/submission-assets.md)
