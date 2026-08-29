# SHRUTI — Architecture

SHRUTI turns N consumer smartphones into one phased microphone array
by synchronising their audio clocks over an ultrasonic chirp and
streaming UNPROCESSED PCM to a laptop array processor over Wi-Fi
Direct. The laptop runs the cross-correlation sync, GCC-PHAT
localisation, delay-and-sum and MVDR beamforming, and an on-device
ASR pass-through. The phones do nothing DSP-heavy; they capture,
heartbeat, and stream.

This document is the engineering reference. Read it top-to-bottom on
day one of onboarding, and refer back when a specific subsystem
moves under your feet.

## Bird's-eye view

```
   ┌─────────────────── LAPTOP (array processor) ───────────────────┐
   │                                                                │
   │   ingest (WebSocket)  →  sync (chirp xcorr)  →  TDOA (GCC-PHAT)│
   │       │                       │                     │          │
   │       ▼                       ▼                     ▼          │
   │   ring buffer            aligner (offsets)     radar (position)│
   │       │                       │                     │          │
   │       └────────► beamform (D&S / MVDR)  ◄──────────┘          │
   │                       │                                       │
   │                       ▼                                       │
   │                  ASR (interface) → transcript pane             │
   │                       │                                       │
   │                       ▼                                       │
   │                TTS readback + overlays → screen mirror         │
   │                                                                │
   │   metrics (counters/gauges) → :8766 /metrics  → dashboard      │
   │   log (JSON or human)        → stderr → shipping               │
   └────────────────────────────────────────────────────────────────┘
        ▲                                           │
        │ Wi-Fi Direct (Office Kit on iQOO)         │
        │ packets, ~2 KB / 20 ms                    │
   ┌────┴──────────────────────────────────────────┴────────┐
   │  PHONE A (master)        PHONE B (element)   PHONE C  │
   │  foreground capture      foreground capture  …       │
   │  UNPROCESSED @ 48 kHz                             │
   │  chirp beacon every 2 s (master only)              │
   │  heartbeat keep-alive against Funtouch killer      │
   └─────────────────────────────────────────────────────┘
```

The chirp handshake is the physics anchor. Everything downstream
relies on its sub-100-µs precision.

## Components

### `apps/android/protocol` — the shared wire format

A pure-JVM Kotlin module that defines and validates the packet
format, with a self-tested CRC-32C (Castagnoli, polynomial
0x1EDC6F41). The reference implementation is
`apps/laptop/shruti_array/protocol.py`; the two MUST stay
byte-compatible.

Wire format (30-byte header + PCM payload + 4-byte CRC):

| Field          | Size | Notes                                    |
|----------------|------|------------------------------------------|
| magic          | u32  | `0x53555254` ('SHRT', little-endian)     |
| version        | u8   | 1                                        |
| type           | u8   | 0x01 audio, 0x02 chirp-echo, 0x03 hb     |
| flags          | u8   | bit 0 dropped, bit 1 last                |
| phone_id       | u8   | 0..254                                   |
| sequence       | u32  | monotonically increasing per phone       |
| sample_rate    | u32  | Hz (48000 on the iQOO fleet)              |
| sample_count   | u16  | int16 samples in the payload (≤ 16384)  |
| reserved       | u32  | must be zero on send                     |
| timestamp_us   | u64  | phone's monotonic clock at send          |
| payload        | i16×| int16 LE PCM                              |
| crc32c         | u32  | over header + payload                    |

The maximum legal packet is `HEADER_SIZE + 16384 * 2 + CRC_SIZE =
32802` bytes. The ingest server refuses anything larger before even
computing a CRC, so a hostile phone can't tie us up in CRC
computation.

### `apps/laptop/shruti_array/sync/` — clock alignment

The master phone plays a 60 ms PRBS-modulated sine sweep in the
ultrasonic band (17.5-22 kHz) every 2 s. Each element phone
records the chirp via UNPROCESSED capture, and the laptop
cross-correlates the reference chirp against each recording to
estimate the per-phone clock offset.

`correlation.find_offset_sub_sample` returns a fractional-sample
offset via parabolic interpolation of the cross-correlation peak.
`alignment.StreamAligner` maintains the latest offset per phone and
tracks drift as a parts-per-million estimate derived from the
packet timing history.

A drift exceeding `SyncConfig.max_drift_ppm` (default 50 ppm)
re-runs the chirp handshake on the next heartbeat.

### `apps/laptop/shruti_array/tdoa/` — direction finding

`gcc_phat.gcc_phat(x, y)` returns the TDOA between two channels via
the Generalised Cross-Correlation with Phase Transform (PHAT
whitening). The batch helper `gcc_phat_batch` runs the estimator on
overlapping windows and returns one TDOA per hop. The radar consumes
the median across windows for robustness.

`radar/position.py` consumes pair-wise TDOAs and solves for the
speaker's 2D position via non-linear least squares (Gauss-Newton
with multiple initialisations to escape local minima).

### `apps/laptop/shruti_array/beamform/` — the spatial filter

`das.delay_and_sum` is the simplest possible beamformer: phase-shift
each channel to align with the steering direction, then average.
Good enough for the demo's "RAW -> BEAMFORMED" toggle moment.

`mvdr.mvdr_beamform` is the Minimum Variance Distortionless Response
beamformer with sub-frame covariance estimation. It needs many
independent snapshots to form a full-rank covariance, so the
regression harness averages across 16 sub-frames of 4096 samples
each. With longer recordings the production code should use an
exponential moving average instead.

`steering.delays_for_direction` returns per-element delays in
samples; the convention is "positive delay = element hears earlier,
must be delayed to align with the centroid." This convention is
mirrored in the protocol: the laptop's ingest assigns a master
phone (the chirp source) and aligns every other phone to it.

### `apps/laptop/shruti_array/ingest/` — network layer

`websocket_server.PacketServer` accepts one WebSocket connection
per phone. Per-connection state is in `PhoneConnection`. The server
enforces:

- a 32802-byte per-frame size cap (before CRC),
- a sliding-window rate limit (400 packets / 2 s),
- a per-phone monotonic sequence check (drops duplicates and
  counts gaps in the sequence),
- a bounded per-phone queue (64 packets, drops oldest on overflow).

`metrics_server.MetricsHTTPServer` is a separate process that serves
`/metrics` (OpenMetrics text) and `/healthz` on a different port.
This keeps the WebSocket and HTTP transports cleanly separated and
lets a dashboard scrape the metrics without holding a WebSocket
connection.

### `apps/laptop/shruti_array/harness/` — regression testing

`synthetic.two_speaker_scene` generates a deterministic multi-channel
scene with a target speaker at a known azimuth and an interferer
elsewhere. `regression.run_synthetic_suite` runs the suite and
emits a JSON report with per-scene SI-SDR for delay-and-sum and
MVDR. The smoke gate ("MVDR is not catastrophically worse than
D&S") lives in `tests/test_beamform.py`; the recorded-corpus gate
("MVDR beats D&S by at least 3 dB on a real noisy room") is
manual, run before each event.

### `apps/android/app` — the phone side

A Kotlin/Compose foreground service app. `CaptureService` opens an
`AudioRecord` with `MediaRecorder.AudioSource.UNPROCESSED` and
streams 20 ms frames to the laptop; `ChirpService` plays the
ultrasonic chirp on the master phone and a keep-alive heartbeat
(monotonic per-heartbeat sequence counter, not a constant zero
which the laptop's monotonic-sequence check would silently drop);
`TransportClient` is an OkHttp WebSocket client (`ws://<laptop>:8765/`)
with exponential backoff (0.5 s → 1 s → 2 s → 4 s → 8 s) and a
bounded queue that drops the oldest packet on overflow (never clears
the whole queue). The wire format inside each WebSocket binary
frame is byte-identical to the legacy raw-TCP path: 30-byte header +
PCM payload + 4-byte CRC.

Phone identity (phoneId 0/1/2, isMaster, laptop WS URL) is read
from `IdentityConfig`, a SharedPreferences-backed singleton that
MainActivity edits through a setup screen. Per-device identity
survives app restart. The capture service also requests
`RECORD_AUDIO` (and `POST_NOTIFICATIONS` on 13+) before starting,
so a denied permission shows a clear message instead of a silent
stop.

The device-bound gaps are clearly marked `NEEDS-DEVICE` in the
source. The team finishes them on the loaner fleet following
`tools/rebuild/recipe.md`.

## Data flow: one audio frame, end to end

1. The element phone captures 960 int16 samples (20 ms at 48 kHz)
   with `UNPROCESSED`. `CaptureService` packs them into a binary
   packet (30-byte header + 1920-byte payload + 4-byte CRC).
2. `TransportClient` writes the packet to the laptop over an
   OkHttp WebSocket on `ws://<laptop>:8765/` (Office Kit Wi-Fi
   Direct in production, loopback in dev). Each WebSocket binary
   frame carries one full packet.
3. The laptop's `PacketServer` reads the packet, checks the size
   cap, verifies the CRC, validates the sequence, applies the rate
   limit, and pushes it onto the per-phone ring buffer.
4. The DSP loop pops the packet, converts int16 to float32, and
   drops the samples into the per-phone ring aligned to the
   master's clock using the latest offset + drift.
5. Once all phones have produced an aligned window of 4096
   samples, the beamformer (D&S or MVDR) produces a beamformed
   signal.
6. The beamformed signal feeds the ASR interface. The default
   `MockASR` returns a placeholder; the team plugs in the
   QNN-exported IndicWhisper at event time.
7. The transcript lands in the overlay, which the laptop screen
   mirrors to the master phone.
8. The toggle (`RAW -> BEAMFORMED`) flips the beamformer selection
   on the next frame.

## Why the synthetic "production ready" gate is the right call

A real corpus on real phones is the only way to prove MVDR's value,
but the synthetic suite is what runs in CI on every push. The
synthetic gate is set to "MVDR is not worse than D&S by more than
3 dB" — wide enough to tolerate real-world noise, tight enough
to catch a regression in the DSP. The recorded-corpus gate (run
manually before each event) is the actual proof.
