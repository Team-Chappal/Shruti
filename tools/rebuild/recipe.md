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
`tools/rebuild/dirty-check.sh` script refuses to start a rebuild on
a dirty tree — that's intentional.

## 2. Laptop environment (3 min)

```sh
cd apps/laptop
python -m pip install -e ".[dev,ui]"
make test-fast     # ~2 seconds, no audio device needed
```

The test suite has 39 tests and exercises the protocol packetizer
(including its CRC-32C self-test against the iSCSI test vector),
the chirp generator, the cross-correlation-based offset estimation,
GCC-PHAT, the delay-and-sum and MVDR beamformers, the regression
harness, the device-audit analyzer, the ASR/TTS interfaces, and the
stream aligner. **All 39 must pass before continuing.** If any test
is flaky, that's a bug — the harness is the contract.

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
#   1. Open the app, start a session, hold the phone face-up on the
#      bench for 30 s of silence.
#   2. Pull the per-phone WAV files from /Android/data/dev.shruti/
#      into data/captures/<phone_id>_*.wav.
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
- Red-light mode: close the laptop. Confirm the phone-only
  beamformer still produces a usable signal.

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
