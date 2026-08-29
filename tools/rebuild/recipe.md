# SHRUTI Rebuild Recipe

A step-by-step runbook to rebuild the entire project from a fresh clone
in under 15 minutes. The goal is that on event day, a cold rebuild is
mechanical: the same commands, in the same order, every time, producing
a working demo. If any step fails, the build halts — there is no "push
through and hope" mode.

The recipe is deliberately redundant with the demo runbook. The
rebuild recipe gets the *system* on the laptop and the phones; the
demo runbook turns the system into a presentation. Keep them in sync.

## 0. Prerequisites

- Three iQOO loaner phones, charged, each with a SIM-less data plan
  (we never use cellular, but the OS insists).
- Laptop with Python 3.10+, Java 17 (for the Android build),
  Android Studio Hedgehog/Iguana or newer, and the iQOO USB driver
  installed.
- The hackathon's Wi-Fi credentials (or a confirmed Wi-Fi Direct
  capability on the loaner fleet).
- A known-quiet conference room for the calibration recordings.

## 1. Clone and sync the repo (2 min)

```sh
git clone https://github.com/Team-Chappal/Shruti.git shruti
cd shruti
git checkout main
git pull --rebase
```

If `git status` is dirty at the end of an event day, stop, commit
what you have with a `wip:` prefix, and rebase tomorrow. The
`tools/rebuild/dirty-check.py` script refuses to start a rebuild on
a dirty tree — that's intentional.

## 2. Laptop environment (3 min)

```sh
cd apps/laptop
python -m pip install -e ".[dev,ui]"
# On Windows: ensure the console can render the radar's bullet
# glyph. Setting PYTHONUTF8=1 is belt-and-braces; the demo also
# reconfigures stdout to UTF-8 on first render and offers --ascii
# as a hard fallback for legacy cp1252 consoles.
PYTHONUTF8=1 make test-fast
```

T06: the demo's default ASR is the `MockASR` (deterministic
placeholder, no model download). To use a real Indic model
on event day:

```sh
# 1. Install the sherpa-onnx Python wheel (about 30 MB; not in
#    pyproject.toml because it's only needed for the real run).
pip install sherpa-onnx

# 2. Download a model. The default target is a 40 MB English
#    Zipformer that's small enough to test the wiring; the team
#    replaces the URLs in tools/fetch_asr.py for IndicWhisper
#    or IndicConformer.
python -m tools.fetch_asr --target tiny

# 3. Run with the real engine.
export SHRUTI_ASR_ENGINE=sherpa
python -m shruti_array.cli demo --seconds 10
```

The test suite runs the protocol packetizer (including its CRC-32C
self-test against the iSCSI test vector), the chirp generator, the
cross-correlation-based offset estimation, GCC-PHAT, the
delay-and-sum and MVDR beamformers, the regression harness, the
device-audit analyzer, the ASR/TTS interfaces, and the stream
aligner. **All tests must pass before continuing.** If any test
is flaky, that's a bug — the harness is the contract. Run
`make test` for the full run with coverage; the CI gate is 75%.

```sh
make synth
# Writes 5 deterministic 2-speaker scenes into data/corpus/synth/
```

## 3. Device audit (10 min)

The device audit is the linchpin. If UNPROCESSED doesn't give
phase-coherent capture across the three units, the whole physics
collapses.

```sh
mkdir -p data/captures
# On each phone, run the audit capture:
#   1. Open the app, switch to "Audit mode", tap Record.
#   2. Hold the phone face-up on the bench for 30 s of silence.
#   3. Tap Share / Done — the WAV lands in the app's external
#      files dir, which on Android maps to:
#         /sdcard/Android/data/dev.shruti/files/audit/<phone_id>_<ts>.wav
#   4. Pull the per-phone WAVs:
adb -s <phone> pull /sdcard/Android/data/dev.shruti/files/audit/ \
    data/captures/<phone_id>/
shruti-audit
cat data/audit/report.json | jq '.[] | {phone: .phone_id, rms: .rms_dbfs, noise: .noise_floor_dbfs, sr: .sample_rate_hz}'
```

The three phones should report matching sample rates (48 kHz on the
iQOO fleet), RMS within ±3 dB of each other, and a noise floor
better than -55 dBFS. If any of these is off, the offending phone
gets demoted to a "spare" and the runbook proceeds with the two
phones that pass.

**Go / no-go gate:** write the result into `docs/agents/issue-tracker.md`'s
event log (or a sister file) — a paper trail for the judges.

## 4. Sync spike (5 min)

The 42-microsecond number is the demo's credibility anchor. Prove
it before building anything else.

```sh
shruti-array run-radar   # starts the WebSocket server on :8765
# On the master phone: start a session, hold the master 1 m from
# the other two. Watch the live offset readout in the radar UI.
# Success: offset std < 100 microseconds over 5 minutes, on all
# three phones.
# Failure: drop to 2-phone mode (the runbook's Tier-0 pitch) and
# continue. The story survives a 2-phone submission; it does not
# survive a broken chirp handshake.
```

## 5. Two-phone spine (15 min)

The MVP floor. When this works, the toggle moment works.

```sh
make harness
# Reports SI-SDR for delay-and-sum and MVDR on the synthetic
# corpus. Real on-device validation: record a 30-second noisy-room
# clip, run the recorded corpus, assert the toggle isolates the
# target voice.
```

`make harness` exits non-zero if MVDR regresses by more than 3 dB
against delay-and-sum on the synthetic suite. On real audio the
gate is the `recorded-corpus` mode of the same harness.

## 6. The rest of the pipeline (30 min)

Only after the spine is solid:

- Beamforming: switch D&S -> MVDR. Listen.
- Transcript: feed beamformed audio to the ASR. Watch the words
  appear in the dev pane.
- TTS readback: enable, mute the room mic on the laptop, confirm
  the laptop reads back the transcript.
- Radar: confirm a teammate walking a short arc is tracked.
- Fallback ladder: kill a phone mid-capture. Confirm the array
  keeps going with the remaining elements.
- Stem-replay rung (the laptop-closed recovery): run
  `shruti-array replay data/stems/example/` and confirm the
  radar + beamformed output render from a pre-recorded
  multichannel stem. This is the post-T13 reality of the
  "red light" rung: no on-phone beamformer, but the laptop
  can still demo from a stem when the live transport is gone.

## 7. Commit the recipe (1 min)

```sh
git add data/audit/ data/regression_runs/
git commit -m "Day-of event audit + regression baseline"
git push
```

The git history is part of the demo: judges can `git log` and see
every working-session change. The compliance rule is
*git history proves the code was written on-site* — the recipe
embraces that.

## 8. The five-minutes-before demo checklist

- Laptop plugged in, lid open, screen mirrored to the master phone.
- Three phones on tripods, one at the back of the room, two flanking
  the demo area.
- Battery bank plugged into the master phone, hidden behind a
  tripod leg.
- `shruti-array run-radar` already running.
- Audio media volume on each phone at MAX (the chirp lives in the
  ultrasonic band; some devices gate it on media volume).
- The 2-minute-of-silence recording is loaded and ready to play
  over Bluetooth for the "before" comparison.
- The three backup audio stems (classroom chaos, factory floor,
  street market) are pre-loaded and verified.
- Water. The good luck. The HDMI cable as a last-resort display.
