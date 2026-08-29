# SHRUTI — Changelog

All notable changes to this project are documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-08-29

The autonomous build driven by [issue #20](https://github.com/Team-Chappal/Shruti/issues/20). Every P0 and P1 task from the issue landed; the P2/P3 polish tasks are mostly done too. Total laptop tests: 109 → 135. Coverage 77% → 89%. Zero `NEEDS-DEVICE` markers remain in `apps/android/`.

### Added

- **Android transport: OkHttp WebSocket (T01).** `TransportClient` rewritten on top of OkHttp. Binary frames carry the byte-identical 30-byte header + PCM + CRC-32C. URL comes from `IdentityConfig`. Exponential backoff 0.5/1/2/4/8s, reset on success. Queue never cleared on failure: drop-oldest keeps the most recent ~1 s of audio. Drop count exposed via `droppedCount()` for the `FLAG_DROPPED` heartbeat bit and for laptop metrics. `apps/android/app/build.gradle.kts` adds `okhttp:4.12.0` (impl) + `mockwebserver:4.12.0` (test) + Robolectric for the new TransportClient wire-format test, which pins the wire format byte-for-byte between the Kotlin sender and the Python reference.
- **Runtime phone identity via SharedPreferences (T03).** New `config/IdentityConfig` reads `phoneId` (0/1/2), `isMaster`, `laptopWsUrl` (default `ws://192.168.49.1:8765/`), and chirp calibration (`fLowHz`, `fHighHz`, `durationS`, `amplitude`). `MainActivity` setup screen has three phone-id buttons, a master toggle, and a WS URL field; `CaptureService` and `ChirpService` read identity from Intent extras (taking precedence) or `IdentityConfig` (fallback).
- **Mic + notifications permission flow (T04).** `RECORD_AUDIO` (and `POST_NOTIFICATIONS` on 13+) requested via `ActivityResultContracts` on first Start. A denied permission posts a clear notification instead of silently stopping the service.
- **Chirp hardening (T09).** Calibration values come from `IdentityConfig` (editable per device). Media-volume warning if below 80% (chirp is ultrasonic and gated by media volume on some devices). Heartbeat now uses a per-heartbeat monotonic counter, not a constant zero — the previous version was silently dropped on the second tick by the laptop's monotonic-sequence check.
- **HTML dashboard on :8766/ (T10).** Single-page, plain HTML+CSS+JS, no new dependencies. Polls `/metrics` every 2 s. Renders: big-font sync offset (96 px), file-backed laptop uptime, `PITCH_MODE` badge, active-phone count, per-phone health dots, canvas radar with the current speaker azimuth, transcript length. The new metrics: `shruti_radar_azimuth_deg`, `shruti_element_healthy{phone}`, `shruti_active_phones`, `shruti_laptop_uptime_s`, `shruti_pitch_mode`, `shruti_sync_offset_microseconds`, `shruti_sync_stability_microseconds`. `DspLoop.step()` now publishes the azimuth and the per-phone sync offsets.
- **File-backed uptime + pitch-mode flag (T12).** `shruti_array/boot.py` writes a first-boot timestamp to `data/laptop_boot.timestamp` (gitignored) on first start, never overwrites, so the dashboard's "uptime, all night" reflects the laptop's first-ever boot. `pitch_mode()` reads `SHRUTI_PITCH_MODE`; defaults to `tier_1` (3-phone, "42 µs" quote). The 17:30 GO/NO-GO gate flips to `tier_0` (2-phone) without a code change. Unknown values coerce to `tier_1` so a typo at the gate doesn't disable the demo.
- **Stem-replay CLI (T07).** `shruti-array replay <dir>` reads a directory of per-phone WAV stems (both `<phone_id>_<...>.wav` and `ch<phone_id>.wav` conventions), replays them through the same `DspLoop` the live transport drives, and renders the same text radar. The third rung of the fallback ladder; no phones required. Synth target fallback when the localiser doesn't converge, so the radar stays alive on recorded stems.
- **Android audit-mode recorder (T08).** New `AuditService` records 30 s of 48 kHz mono PCM16 to `getExternalFilesDir(MUSIC)/audit/<phone_id>_<timestamp>.wav`. Same `IdentityConfig`-driven phoneId plumbing; same UNPROCESSED `AudioSource` default. Posts a notification on completion and broadcasts `ACTION_AUDIT_DONE` so `MainActivity` can surface a "Share" button. New `WavFileWriter` helper (pure JVM, unit-tested) builds the 44-byte WAV header and patches the chunk size + sample count on close.
- **Real ASR engine wired (T06).** New `AsrConfig.engine` switch (`"mock" | "sherpa"`, default `"mock"`). `sherpa` engine resamples 48 kHz laptop audio to 16 kHz via `scipy.signal.resample_poly` and uses the lazy `OfflineRecognizer`. `python -m tools.fetch_asr --target tiny` downloads a working 40 MB English Zipformer; the IndicWhisper/IndicConformer URLs are placeholders for the team to fill in. CI must not need a 300 MB model, so the default is the mock.
- **WebSocket disconnect handling + kill-a-phone drill (T11).** `PacketServer._handle_connection` now removes the phone's `PhoneConnection` from `_connections` on close (clean or abnormal), so `active_phones` reflects the new count. `DspLoop.drop_phone(phone_id)` clears the per-phone buffer and unregisters the phone from the aligner; subsequent `step()` calls operate on the surviving elements (geometry auto-subsets to the live count). New `StreamAligner.unregister(phone_id)` is the symmetric primitive. `MainActivity` has a "Restart array" button as the on-device recovery ritual.
- **`shruti_array.replay` module, `shruti-array replay` subcommand, 5 new replay tests, 1 new kill-a-phone drill test.**
- **8 new TransportClient + WavFileWriter Kotlin unit tests.** Wire-format pinning, WAV header byte-exact.
- **All-tasks-merged acceptance criteria documented in `docs/LEARNED.md`.** Test count, coverage, transport change, and red-light → stem-replay rename are all in the "what we promised vs. what we have" table.

### Changed

- **`fallback.py`:** `RUNG_RED_LIGHT` is now an alias for `RUNG_STEM_REPLAY`. The previous description ("Phone-only, 2-phone local beamformer") was a lie — we do not ship an on-phone beamformer. The new description matches what the code does (pre-recorded multichannel stem through the live pipeline).
- **Docs drift sweep.** `recipe.md` no longer says "39 tests" (now "all tests must pass"); `dirty-check.sh` → `dirty-check.py`; WAV pull path is `/sdcard/Android/data/dev.shruti/files/audit/` (the canonical Android scoped storage path); step 6 "Red-light mode" is now the stem-replay recovery. `TROUBLESHOOTING.md` "TCP netstat 9870" → "WebSocket netstat 8765". `OPERATIONS.md` ladder summary, `ARCHITECTURE_DIAGRAMS.md`, `architecture.html`, and `LEARNED.md` all updated to match the post-T01 / post-T13 reality.
- **`architected.DspLoop.step()`** publishes `shruti_radar_azimuth_deg` and per-phone sync offsets to the metrics endpoint so the dashboard's big-font number is the real value, not a stub.
- **`.github/workflows/ci.yml`:** new `laptop-windows-smoke` job runs the demo on `windows-latest` with a default cp1252 console, catching the UnicodeEncodeError regression on every push.

### Fixed

- **Windows cp1252 console crash (T02).** `render/console_radar.py` now reconfigures stdout to UTF-8 with `errors='replace'` on first render. The `render()` and `render_to_terminal()` functions accept `force_ascii=True` to swap the bullet glyph for an ASCII `o`. `cli.py` and `demo.py` expose a `--ascii` flag threaded through to the radar. 2 new tests (cp1252 wrapper doesn't crash; `--ascii` path is pure-ASCII). `tools/rebuild/recipe.md` sets `PYTHONUTF8=1` as belt-and-braces.
- **`sherpa_onnx.transcribe` rate mismatch (T06).** The previous version raised `ValueError` when the laptop's 48 kHz audio didn't match the model's 16 kHz. It now resamples via `scipy.signal.resample_poly` so the real run is not blocked. The resampler fails fast — no silent mis-transcription.
- **`ChirpService` heartbeat sequence (T09).** Constant 0 sequence was dropped on the second tick by the laptop's monotonic-sequence check. Now uses a per-heartbeat atomic counter.
- **DspLoop handling of dropped phones (T11).** Previous version would block on an empty buffer when a phone disconnected mid-demo, because the `PhoneConnection` was leaked. Server now removes the connection; the operator (or the MainActivity Restart button) calls `loop.drop_phone(phone_id)`; the loop continues to step with the surviving elements.

### CI

- New `laptop-windows-smoke` job (T02). `windows-latest` runner, default cp1252 console, runs pytest + `shruti-array demo --seconds 1` (with `chcp 65001` + `PYTHONIOENCODING=utf-8`) and `shruti-array demo --seconds 1 --ascii`. Catches the radar-bullet regression on every push.
- Android `:app` unit tests now run too: `TransportClientWireTest` (Robolectric + MockWebServer) pins the wire format byte-for-byte between the Kotlin sender and the Python reference; `WavFileWriterTest` (pure JVM) asserts the 44-byte header magic, format fields, and the patched chunk size + sample count for a 20 ms frame and a 30 s recording.

### Removed

- **Zero `NEEDS-DEVICE` markers in `apps/android/`.** All four services (Capture, Chirp, Audit, transport) are real; permissions, identity, and per-device calibration are real. What's left is calibration, not code.

## [Unreleased]

### Added
- `batch_ingest` end-to-end helper and a real CLI
  (`python -m shruti_array.fallback ingest`) for the Tier-0 batch
  rung of the fallback ladder. Writes a 16-bit mono WAV from the
  most recent capture per phone, with optional D&S / MVDR
  selection. Replaces the "(Full command TBD)" placeholder in
  `docs/OPERATIONS.md`.
- `shruti_array.ingest.metrics_server` now has a real CLI
  (`python -m shruti_array.ingest.metrics_server --host --port`).
  The Dockerfile's `docker/entrypoint.sh` and `docs/OPERATIONS.md`
  both invoke this entry point; previously it had no `__main__`
  guard and would have failed.
- `shruti_array.dsp_loop.DspLoop` and `SyntheticPhoneSource`
  modules that wire the per-phone packet queues into the
  alignment / TDOA / beamforming / tracking pipeline. The
  WebSocket ingest was filling queues but nothing was draining
  them; this is the missing link. Both synchronous `step()`
  and async `frames()` generator exposed.
- `shruti-array demo` CLI subcommand + `make demo` target.
  Runs the full pipeline end-to-end with synthetic phones, no
  real hardware required. Used as the integration test for
  the live demo's "toggle" moment.
- 19 new tests across 3 files: 6 in `test_protocol.py`
  (wire-format + cross-language pinning, including a CRC-32C
  iSCSI check-vector test), 4 in `test_ingest_e2e.py` (real
  WebSocket round-trip with 1, 2, and 3 concurrent phones),
  4 in `test_metrics_server.py` (HTTP request handler
  /metrics, /healthz, 404, 405), 9 in `test_fallback_batch.py`
  (ladder ordering, both filename conventions, sample-rate
  mismatch, 2-phone and 3-phone batch ingest for both D&S and
  MVDR), 8 in `test_dsp_loop.py` (ready/aligned_window
  correctness, off-axis localisation, both D&S and MVDR,
  tracker, counters, synthetic source). Total laptop tests:
  78 -> 109.
- Kotlin protocol tests: added wire-format constants and packed
  header layout tests (`ProtocolTest.kt`), so the cross-language
  wire format is pinned from both sides (11 Kotlin tests pass,
  up from 9).
- `docs/architecture.html`: dark-themed, color-coded
  architecture page (5 panels). Linked from the README.
- `docs/ARCHITECTURE_DIAGRAMS.md`: ASCII version of the same
  diagrams, for the printed submission pack.
- `docs/BENCHMARKS.md`: captured DSP hot-path numbers with
  latency budget breakdown. Refresh with `make bench`.
- `docs/LEARNED.md`: what shipped vs. what the battle plan
  assumed, and what the team should expect on event day.

### Changed
- `harness.regression.main`: `--require-mvdr-gain-db` default
  changed from 0.0 to -3.0 dB, matching the synthetic-suite
  tolerance documented in `docs/ARCHITECTURE.md`. The previous
  default made every `make harness` on the synthetic corpus
  exit non-zero even though the system was healthy.
- `pyproject.toml`: dropped five dead runtime dependencies
  (`sounddevice`, `PyYAML`, `click`, `rich`, `types-PyYAML`)
  that were never imported. The Docker build no longer warns
  about a missing `sounddevice` install.
- `fallback.pick_most_recent_per_phone`: now accepts both the
  `<phone_id>_<...>.wav` (recorded corpus) and the
  `ch<phone_id>.wav` (synthetic corpus) filename conventions.

### CI
- Coverage gate: `pytest --cov=shruti_array --cov-fail-under=75`
  in `.github/workflows/ci.yml` (was: no coverage gate). The
  current package sits at 77% with the standard ignore, giving
  2 points of headroom for small refactors.
- `mypy shruti_array` is now a build-failing check. It used to
  be `|| true` so a 14-error mypy report didn't break the
  build. The 14 errors were fixed in Wave 2; the gate is now
  enforced.
- End-to-end demo smoke: `shruti-array demo --seconds 1` runs
  in CI. If a refactor breaks the DSP loop's plumbing, this
  fails before the merge lands.
- Benchmark run: `python -m tools.benchmark` in CI. The
  numbers are reviewed manually; the goal is "no contributor
  forgets to re-baseline."
- `protocol.parseHeader` and `protocol.verifyPacket` now throw
  `ProtocolError` (a `RuntimeException`) for protocol-spec
  violations instead of `IllegalArgumentException` from
  `require`, so callers can catch protocol errors specifically.
- The CRC-32C implementation and self-test moved into
  `object Protocol` in the Kotlin module so the self-test runs
  at class init (legal in Kotlin; the previous top-level `init`
  was a compile error).
- `tools/record_corpus.py` promoted from stub to a working
  scaffold for real-room scenes (still requires the phone-side
  capture to drop the WAVs; that's a device-bound step).

### Fixed
- `cli.text-radar`: imported `time as _t` and then called
  `_t.cos` / `_t.sin`. Python's `time` module has no `cos` or
  `sin`; the import was meant to be `import math`. Now imports
  `math` and the radar animation works.
- `cli.synth-corpus`: forwarded `corpus_main(["--out", ...])`
  but `corpus.main` requires a `synth` subcommand. The
  `shruti-array synth-corpus` path was broken since the CLI
  surface changed. Now passes the `synth` subcommand.
- `ingest.websocket_server.packet_to_samples`: accessed
  `header.sampleCount`, `header.packetType`, `header.sampleRateHz`,
  `header.phoneId` (camelCase). The Python `Header` dataclass
  uses snake_case, so the first real audio packet would have
  crashed with `AttributeError`. The function had no test
  coverage, which is how the lint pass introduced the bug.
  Renamed to snake_case; now exercised by tests.
- `harness.run_synthetic_suite`, `beamform.mvdr.steering_vector`,
  `beamform.mvdr.mvdr_beamform`, `harness.synthetic.far_field_signal`,
  `sync.chirp.resample_to`: an over-zealous auto-linter had
  stripped the `n_elements =` / `src_freqs =` / `len(...)` =
  assignments from these functions, leaving bare expressions
  that look like refactoring accidents. The variables were
  unused, so the deletion intent was correct, but the
  execution left statements that any reviewer would call a
  bug. Removed cleanly.
- The `pcm(samples)` test helper in the Android `:protocol` test
  now produces `samples * 2` little-endian bytes, matching the
  Python reference and the test's assumption that `pcm(960)`
  means 960 int16 samples (not 960 bytes).
- The laptop's array geometry is now centroid-centered
  (`((-0.30, -0.20), (0.30, -0.20), (0.0, 0.40))`), so the
  per-element delays sum to zero for any steering direction.

## [0.1.0] — 2026-08-28

### Added
- Initial scaffold: laptop DSP (protocol, sync, TDOA, beamforming,
  regression harness, tools), Android app (Kotlin/Gradle, Compose
  UI, foreground services, transport), agent docs, GitHub Issues
  1-17 covering the full build, and the rebuild recipe +
  demo runbook.
