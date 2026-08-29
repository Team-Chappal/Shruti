# Recording a real noisy-room scene

The synthetic corpus is the smoke gate; the recorded corpus is the
real one. A real recording needs:

- Three phones in a known geometry (the standard triangle, ~60 cm
  on a side).
- A target speaker at a known azimuth (use a tape measure and a
  laser pointer if you have one).
- Optionally, an interferer at a different azimuth.
- A quiet-but-not-silent room: HVAC, distant chatter, a fan. Not a
  recording studio.

## Before you start

1. Verify the device audit passes for all three phones (recipe
   step 3). If a phone's noise floor is poor, replace it.
2. Pick the room and the geometry. Photograph the setup. The photo
   goes in the scene's `meta.json` later.
3. Confirm the chirp sync is solid for at least 5 minutes of stable
   capture (recipe step 4). The scene recording is meaningless
   without solid sync.

## Capture

Run the scaffold:

```sh
python tools/record_corpus.py \
    --out data/corpus/recorded/2026-08-28_classroom \
    --name classroom_scene_01 \
    --room "Bengaluru conference room A" \
    --target-azimuth-deg 20 \
    --interferer-azimuth-deg -45 \
    --duration-s 60 \
    --notes "Two-speaker scene, HVAC on, doorway chatter"
```

This creates the directory and `meta.json`. Now start the capture
on each phone. The app's audit mode (T08) writes WAVs to the app's
external files dir, which on Android maps to:

    /sdcard/Android/data/dev.shruti/files/audit/<phone_id>_<ts>.wav

```sh
# On each phone, via adb, start an audit-mode capture:
adb -s <phone> shell am start -n dev.shruti/.capture.CaptureService \
    --es mode audit \
    --es output_dir /sdcard/Android/data/dev.shruti/files/audit/
```

Run the scene for the configured duration. Stop the service. Pull
the WAVs:

```sh
adb -s <phone> pull /sdcard/Android/data/dev.shruti/files/audit/ \
    data/corpus/recorded/2026-08-28_classroom/
```

## Validate

```sh
make harness
# ... but point the harness at the recorded corpus:
python -m shruti_array.harness.regression \
    --scenes 1 \
    --duration-s 60 \
    --out data/regression_runs/recorded.json
```

The real-corpus gate is what proves MVDR's value over delay-and-sum
on noisy rooms.

## Notes

- Per-scene WAVs go straight into version control *only* if the
  scene is short and the recording is clean. A 60-second mono
  WAV is 5.7 MB; ten scenes is 60 MB. Larger or noisier scenes
  live outside the repo and are referenced by hash in `meta.json`.
- The first recording of the day always has a few seconds of
  garbage at the start (the foreground service warm-up, the
  sync handshake finishing). Trim the first 5 seconds with
  `ffmpeg -i in.wav -ss 5 trimmed.wav` before adding to the
  corpus.
