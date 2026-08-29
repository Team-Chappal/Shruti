# SHRUTI — Troubleshooting

Symptoms, causes, and fixes. Most of these are also surfaced by
the metrics endpoint; if you can `curl` it, start there.

## "No phones connected" (active_phones = 0)

- Are the phones on the same Wi-Fi Direct group as the laptop?
  The Office Kit bridge handles this; check the bridge status.
- Is the WebSocket connection open? `netstat -an | grep 8765` on
  the laptop, or check the phone app's status bar (it shows the
  WebSocket connection state).
- Is the laptop firewall blocking port 8765? `sudo ufw allow
  8765/tcp` on Linux; Windows Firewall allow inbound on 8765.

## "Sync offset > 100 us" or unstable

- The chirp handshake re-runs on the next heartbeat (2 s). If
  the offset is consistently high, the master phone's speaker
  may be too quiet — bump media volume to max.
- If only one phone has a high offset, that phone is the
  outlier. Demote it to spare and run on 2 phones (the Tier-0
  pitch).
- If the offset drifts up over minutes, the phone's clock is
  losing sync. Reboot that phone.

## "CRC failures" increasing

- A few CRC failures per minute are normal (Wi-Fi interference).
  If it exceeds 1% of packets received, the Wi-Fi channel is
  congested. Move the laptop and the master phone closer, or
  switch to a less-crowded 5 GHz channel.
- A single phone generating 100% CRC failures has a capture
  problem. Check the WAV audit; replace the phone.

## "Audio stutters or the toggle does nothing"

- The `shruti_dropped_frames_total` counter is climbing: the
  beamformer is being starved of data. The most common cause
  is the ASR hanging — check the laptop CPU and the ASR
  backend's queue depth.
- The toggle: confirm the laptop is actually switching
  beamformers. `shruti_beamform_output_db` should change
  amplitude when you flip the toggle.

## "The radar dot is jittery or stuck"

- GCC-PHAT is noisy on quiet frames. The tracker
  (`shruti_array.tracker`) drops tracks that haven't been
  updated in 2 s. If the dot is stuck, the speaker has been
  silent for too long; clap once and the dot will reappear.
- If the dot is in the wrong corner by 90 degrees, the element
  geometry on the laptop is wrong. Check `ArrayConfig.geometry`
  in `config.py`.

## "Tests fail locally but pass in CI (or vice versa)"

- Python version mismatch. The project targets 3.10, 3.11, 3.12.
  Use `python -m pip install -e ".[dev]"` to install the pinned
  dev deps.
- The synthetic corpus is seeded; the tests should be
  deterministic. If you see flake, it's almost always the
  GCC-PHAT single-frame tests on a hostile random seed; run
  them in isolation.

## "Android :protocol:test fails after a Kotlin change"

- The protocol is byte-compatible with the Python reference.
  If a test fails, the most common cause is a CRC-32C
  self-test failure at object init, which crashes the whole
  module. Check the build log for "CRC-32C self-test failed."
- Toolchain mismatch: the build uses whatever JDK runs Gradle.
  Set `org.gradle.java.installations.paths` in
  `gradle.properties` if you need a specific JDK.

## "Gradle can't download the wrapper distribution"

- The wrapper points at `services.gradle.org`. If the venue has
  no outbound internet, pre-stage the distribution in
  `~/.gradle/wrapper/dists/` or set the
  `distributionUrl` in `gradle/wrapper/gradle-wrapper.properties`
  to a local mirror.
