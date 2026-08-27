# Shruti

> Three phones. One microphone. Zero mercy for noise.

**SHRUTI** fuses multiple smartphones into a single phased microphone array. Built for the iQOO Hackathon 2026 - City Battles (Smart Education track, Bengaluru).

## How it works

1. **Ultrasonic chirp handshake** synchronizes the phones' audio clocks.
2. **TDOA localization** finds the speaker in the room (radar view).
3. **Beamforming** steers a virtual mic at the speaker and suppresses everything else.
4. **Offline Indic ASR** on the Snapdragon NPU produces a clean, vernacular transcript.

All local. No cloud. No internet.

## Stack

- Android (Kotlin) - capture + UI
- DSP - chirp sync, GCC-PHAT TDOA, delay-and-sum + MVDR beamforming
- ONNX Runtime + QNN - on-device ASR
- WebSocket transport (Office Kit Wi-Fi Direct in production)

## Repo layout

```
apps/
  laptop/              # The array processor (Python, 70+ tests, ~75% coverage)
    shruti_array/
      protocol.py      # Wire format + CRC-32C (Castagnoli, iSCSI test vector)
      sync/             # Chirp gen, cross-correlation, alignment + drift
      tdoa/             # GCC-PHAT
      beamform/         # Delay-and-sum + MVDR
      radar/            # 2D position from pair TDOAs
      ingest/           # WebSocket server + standalone /metrics HTTP
      harness/          # Regression: synthetic corpus + SI-SDR report
      fallback.py       # Degradation ladder
      tracker.py        # Multi-speaker tracker
      render/           # Text-based radar UI + judge-facing overlays
      asr/ tts/         # ASR/TTS interfaces + sherpa-onnx/Piper scaffolds
      tools/            # Audit + corpus generators
    tests/              # 70 tests, all green
  android/             # Kotlin/Gradle app (Compose UI, foreground services)
    protocol/           # Byte-compatible Kotlin port of the wire format
    app/                # CaptureService, ChirpService, TransportClient
docs/                  # ARCHITECTURE, OPERATIONS, SECURITY, TROUBLESHOOTING, CLI
tools/                 # rebuild recipe, demo runbook, record-corpus, benchmark
.github/workflows/     # ci (laptop tests + Android protocol), release (sdist/wheel + Docker)
Dockerfile             # Laptop processor image
```

## Quick start

### Laptop (the array processor)

```sh
cd apps/laptop
python -m pip install -e ".[dev]"
make test           # 70 tests, ~1s
make bench          # microbenchmark
shruti-array text-radar --seconds 5   # headless radar smoke
shruti-array run-radar                # production run
```

### Android (the phone)

```sh
cd apps/android
./gradlew :protocol:test              # 9 JVM tests
./gradlew :app:assembleDebug           # needs Android SDK
```

### Rebuild recipe (the day-of-event runbook)

See [tools/rebuild/recipe.md](tools/rebuild/recipe.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status

- 70 laptop tests passing, ~75% line coverage, ruff clean.
- 9 Android protocol tests passing (byte-compatible with the Python reference).
- CI runs the laptop suite on Python 3.10/3.11/3.12 and the Android protocol on every push.
- Release workflow builds sdist + wheel and a Docker image on tag push.

## Device-bound gaps

These ship as `NEEDS-DEVICE` markers in the source and are completed on the loaner fleet at the venue:

- UNPROCESSED capture verified on the 3 real iQOO phones
- ONNX→QNN export of the Indic ASR running on the Snapdragon NPU
- Office Kit Wi-Fi Direct bridge host IP
- The actual measured 42-µs sync number

## Team

Team Chappal - iQOO City Battles 2026, Bengaluru.

## Docs

- [Battle plan](./SHRUTI_BATTLE_PLAN.md)
- [Two-week refinement](./docs/ideas/shruti-two-week-refinement.md)
- [Agent config](./AGENTS.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [Operations runbook](./docs/OPERATIONS.md)
- [Security & trust model](./docs/SECURITY.md)
- [Troubleshooting](./docs/TROUBLESHOOTING.md)
- [CLI reference](./docs/CLI.md)
- [Changelog](./CHANGELOG.md)
- [Rebuild recipe](./tools/rebuild/recipe.md)
- [Demo runbook](./tools/rebuild/demo-runbook.md)
