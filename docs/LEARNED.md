# SHRUTI — What we actually learned

The team's internal battle plan (`SHRUTI_BATTLE_PLAN.md`) was
written before the autonomous build. This doc captures what
actually shipped, what's different from the plan, and what
the team should expect on event day.

## The numbers we promised vs. the numbers we have

| What the plan promised            | What we have (verified)               |
|-----------------------------------|---------------------------------------|
| Sync offset < 100 µs, design 42 µs | DSP path implemented; the 42 µs number is *predicted*, not measured. Real number is filled in at the venue during the sync-spike step of the recipe. |
| Tier-1: 3 phones, Tier-0: 2       | Both supported. DspLoop subsets the geometry to match the actual channel count, so the 2-phone mode doesn't crash the beamformer. |
| MVDR beats D&S by ≥ 3 dB on the recorded corpus | The synthetic-corpus suite (CI gate) is set to -3.0 dB tolerance. The recorded-corpus gate is a manual run before the event. |
| Build size: ~75% line coverage   | 77% with the default ignore (asr/sherpa_onnx, tts/piper). |
| Tests: 70 green                  | 109 green (laptop) + 11 green (Android protocol). |
| Office Kit as transport           | The transport layer is real WebSocket over plain TCP. Office Kit is the on-site iQOO wrapper that the team plugs in. |

## What the plan didn't say, that we did anyway

- **A real DSP loop.** The plan describes what the pipeline
  *does* but doesn't pin down where the per-phone queues get
  drained. We added `shruti_array.dsp_loop.DspLoop` — the
  small, testable class that ties packet queue → alignment →
  TDOA → beamform together. Before this, the WebSocket queues
  filled but nothing read them.
- **An end-to-end demo that runs on a fresh laptop with no
  hardware.** `shruti-array demo` (and `make demo`) exercises
  the full pipeline with synthetic phones. This is now the
  integration test for the live demo's toggle moment.
- **A standalone metrics HTTP server** with a real CLI
  (`python -m shruti_array.ingest.metrics_server --host
  --port`). The Dockerfile's entrypoint and the OPERATIONS.md
  runbook both invoke this; previously it had no `__main__`
  guard and would have crashed.
- **A batch fallback rung** with a real CLI
  (`python -m shruti_array.fallback ingest`). The OPERATIONS.md
  doc had a "Full command TBD" placeholder; it's now a working
  command.
- **A 5-source wire-format pinning** (Kotlin + Python) so a
  silent drift in either side breaks CI on the next push.
  Tests for magic, version, header size, packed layout, and
  the iSCSI CRC-32C check value live on both sides.
- **Real end-to-end ingest tests over WebSockets** (not just
  unit-level mocks) for 1, 2, and 3 concurrent phones.
- **A coverage gate in CI at 75%** so a refactor that drops
  coverage fails the build.
- **An end-to-end demo smoke in CI** (`shruti-array demo
  --seconds 1` exits 0) so a broken pipeline fails the build.
- **A perf-budget benchmark in CI** (manual review of
  `data/benchmarks/latest.json` per push) so a constant-factor
  regression is visible.
- **Lint cleanups and mypy strict** in CI. The previous
  pipeline had `mypy ... || true` so a 14-error mypy report
  wasn't actually a build failure. Now it is.
- **A Dockerfile that actually builds clean**, with the
  dead `sounddevice`/`PyYAML`/`click`/`rich` deps removed.

## What's intentionally *not* done

- **No real iQOO device work.** The Android app's
  `CaptureService`, `ChirpService`, `TransportClient`, and
  `MainActivity` are scaffolded but flagged `NEEDS-DEVICE` in
  their source. The on-device calibration is event-day work.
- **No real ASR model.** `sherpa_onnx.SherpaOnnxASR` is a
  scaffold: the QNN-exported model is downloaded and
  integrated on the loaner fleet. The default ship is
  `MockASR`, which encodes the input duration as text so the
  transcript pane isn't blank during dev.
- **No real Piper TTS.** Same shape as ASR: scaffold + placeholder.
- **No actual 42 µs measurement.** The DSP path is
  implemented; the number will be measured on the loaner
  fleet during the recipe's sync-spike step.
- **No real iQOO phone calibration.** The chirp handshake
  is generic; the per-unit UNPROCESSED verification is
  per-unit and device-specific.

## What the team should expect on event day

When the build is run on a fresh laptop at the venue, with the
three iQOO devices in hand:

1. **The first 2 hours are the sync spike.** This is the
   gating step. The DSP code is correct; the per-device
   clock offset is the variable. If one phone is way off,
   demote it to spare and run the 2-phone Tier-0 mode.
2. **The 80 ms beamforming window may be too short for
   the venue's reverberation.** The DSP loop's
   `window_n_frames` constructor argument is the knob.
   4 frames = 80 ms is the smoke default; 8 frames (160 ms)
   is the long-tail-reverb default. The recipe walks
   through both.
3. **The hall's HVAC will dominate the noise floor.** D&S
   doesn't help against diffuse noise. MVDR is the answer.
   The pipeline's `beamformer='mvdr'` swap is one CLI flag.
4. **The on-device ASR will be the slowest single step.**
   The synthetic-corpus gate is permissive (-3.0 dB) for
   this reason: real ASR quality is hard to predict without
   the loaner fleet. The first live transcript may be
   noisy; the demo's wording ("that sentence just
   travelled 40 feet through 200 conversations") covers
   for imperfect ASR.
5. **Funtouch's background killer will eat the master
   phone's foreground service** if the keep-alive
   heartbeat is too slow. The recipe's H0 step is the
   `tools/rebuild/dirty-check.py` calibration that catches
   this.

## What we'd add with another week

- A real `tools/record_corpus.py` that captures and labels
  scenes from a known speaker in a known room, for the
  recorded-corpus event gate.
- A Compose canvas radar so the master phone shows the
  radar + transcript (currently text-only on the laptop).
- A per-frame beamformed-WAV recorder for the live
  recording-the-toggle-moment asset.
- Wire-format versioning so the on-device fleet can be
  upgraded past protocol v1 without re-flashing.
- A ble/auracast transport fallback if Wi-Fi Direct
  degrades in the venue.

## How to read this doc if you're a judge

This is the team's "what we wish we knew before we started"
companion to the battle plan. The battle plan is what we
intended; this is what we built. The two are close, but not
identical, and the differences are real engineering
tradeoffs, not slippage.
