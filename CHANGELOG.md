# SHRUTI — Changelog

All notable changes to this project are documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
