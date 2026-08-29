# Demo video script (SHRUTI, iQOO City Battles 2026)

This is the script for the 2-3 minute demo video. The video
must be uploaded before the venue round to qualify. Read this
top-to-bottom before recording.

## What the video must show (in order)

1. **Cold-start proof** — the laptop has no Python venv active.
   You record yourself running `make install && make test && make
   demo` from a fresh terminal. Total time: ~30 s.

2. **Synthetic demo running** — `shruti-array demo --seconds 5`
   shows the text radar moving on the laptop, the synthetic
   target tracking. ~20 s.

3. **Real hardware** — show the two real phones (realme + Nothing)
   with the SHRUTI app open and the "Start" button visible. You
   tap Start on phone 0, the laptop's `run-radar` log shows
   `phone 0 registered` within 1 second. You tap Start on phone 1,
   the log shows `phone 1 registered`. ~30 s.

4. **The toggle** — you point the phones at a sound source
   (your own voice, a Bluetooth speaker, anything). The
   laptop's text radar immediately tracks the source. ~20 s.

5. **The soaks / gates** — you flip to a terminal showing
   `pytest -q` running and ending with `235 passed, 1 xfailed`.
   ~10 s.

6. **A taste of "we have 8 production items left"** — a single
   line of voice-over about the LEARNED.md items, then the
   outro card.

## What the video must NOT show

- The Android Studio IDE — too heavy, won't open on the demo
  laptop.
- Compilation logs — boring, no judge is interested in 30 s of
  gradle output.
- The actual mic arrays / speakers (a single realme+Nothing
  is enough; you don't need 3 phones for the demo).
- Any failure modes — if `make test` fails, restart the
  recording, do not edit around it.

## What you say

Total voiceover: ~30 s. Keep it under 60 s.

> "SHRUTI is three iQOO phones that act as a phased microphone
> array. Audio streams over WebSocket to a laptop that does
> chirp-based sync, GCC-PHAT TDOA, and delay-and-sum
> beamforming. The result is real-time speaker tracking in text
> form, with the demo target also exported as a WAV via
> `shruti-array demo --record-toggle`.
>
> In the next 90 seconds you'll see: the laptop's test suite
> passing, a synthetic 3-phone pipeline, and two real phones
> streaming to the laptop in real time. Note the sync spike
> lands at 42 microseconds."

(The 42 µs is the synthetic demo's known-good number. If the
real-device number is different, use the real number — the
judge will appreciate the honesty.)

## What to do before recording

```bash
# Kill any leftover run-radar
powershell -NoProfile -Command \
  "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
   ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force }"

# Cold-start python
cd C:/Users/DELL/OneDrive/Desktop/shruti
cd apps/laptop
rm -rf .venv
python -m venv .venv
source .venv/Scripts/activate
pip install -e ".[dev]"
pytest -q
shruti-array demo --seconds 5
```

If any of these fail, **stop and fix the failure**. Do not
record a broken demo.

## What to do during recording

- **Camera 1**: face the laptop screen, frame the full
  terminal. Crop to show the prompt, the output, and the radar.
- **Camera 2 (phone or second laptop)**: a wide shot of the
  desk with the two phones propped up, the laptop visible, and
  you visible. Use this for the voiceover.
- **Audio**: your voice. No background music. The room should
  be quiet enough that the phones pick up your voice from 1 m
  away.

## Recording checklist

Before you hit "record", confirm:

- [ ] Both phones connected to the venue Wi-Fi (or, if testing at
      home, the same Wi-Fi the laptop is on).
- [ ] Laptop's `shruti-array run-radar` is running.
- [ ] Both phones have `ws_url` set to the laptop's Wi-Fi IP
      (the SHARED address on the venue Wi-Fi).
- [ ] `am start -n dev.shruti/.ui.MainActivity` on each phone
      brings up the SHRUTI app with the WS URL field pre-filled
      and the phone-id button highlighted.
- [ ] A sound source within 2 m of the phones — your mouth is
      fine, or a phone playing a podcast at 30% volume.
- [ ] Recording light: the laptop screen readable, the phone
      screens readable, your face visible.

## After recording

- Trim to 2:30-3:00. Judges don't watch 4-minute videos.
- Add a 1-second fade-to-black between sections 2/3/4/5.
- Add a 3-second end card with the repo URL, the project name,
  and "SHRUTI / iQOO City Battles 2026".
- Upload. Save the source video (not the compressed version) in
  `data/demo-video/` so the team has a high-quality copy.

## What to do if something goes wrong

- **Laptop loses Wi-Fi mid-recording**: pause, reconnect, re-run
  the demo, resume.
- **Phone drops WS**: tap Stop, tap Start again. The laptop's
  `run-radar` will log `phone 0 disconnected; active=2` then
  `phone 0 registered; active=3` within 2 s. The audio radar
  will skip ~0.5 s of frames.
- **`make test` fails on a single test**: do not edit around
  it. Diagnose. If it's the known `test_gcc_phat_anticorrelation_still_zero_lag`
  xfail, that's fine, it's an xfail. If it's a real failure,
  fix it before re-recording.
- **You say the wrong number for the sync spike**: cut, redo
  the line, re-record. A wrong number in the voiceover is
  worse than a re-take.

## What the judge will look for

1. **Does it work end-to-end on real hardware?** This is the
   single most important thing. If the toggle moves, you pass.
2. **Is the architecture explained?** The 30-second voiceover
   covers chirp + TDOA + beamforming. That's the right depth.
3. **Are there known limitations, honestly stated?** The
   LEARNED.md table is the judge-facing version. "We have 8
   production items left" is a sign of engineering maturity,
   not weakness.
4. **Will it work at the venue?** Yes, if the venue has a
   normal Wi-Fi AP. The video should mention this.

## What the judge will NOT care about

- Whether the test suite takes 14 s or 30 s.
- Whether the radar is a text radar or a canvas radar (text is
  fine; the doc says Compose canvas is on the post-event list).
- Whether the ASR is real or mocked (the demo is audio routing,
  not ASR).
- Whether the protocol is at version 1 or 1.0.0.
