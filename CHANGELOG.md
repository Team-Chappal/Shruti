# SHRUTI — Changelog

All notable changes to this project are documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Structured JSON logging (`SHRUTI_LOG_FORMAT=json`) and a
  lightweight in-process metrics registry with OpenMetrics
  exposition via a standalone `/metrics` HTTP server.
- Per-packet size cap, sliding-window rate limiter, and bounded
  per-phone queue in the WebSocket ingest server. Counters for
  received/rejected/decoded/CRC-failure/dropped-frames/active-phones.
- Architecture, Operations, Security, Troubleshooting, and CLI
  reference documents under `docs/`.
- `apps/android/gradlew`, `gradlew.bat`, and `gradle-wrapper.jar`
  so the Android side builds with `./gradlew :protocol:test` and
  no system Gradle install required.
- Dockerfile for the laptop processor and a release workflow that
  publishes a versioned GitHub release on tag push.
- `pytest-asyncio` integration tests for the ingest server
  (size cap, rate limit, CRC failure, valid registration).
- Standalone metrics HTTP server (`ingest/metrics_server.py`).

### Changed
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
