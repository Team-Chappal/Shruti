# SHRUTI — Architecture diagrams

Two views of the same system. The HTML version (`architecture.html`)
is the live, linked, dark-themed reference; the ASCII block below
is what the team pastes into the printed submission pack (per
`docs/submission-assets.md`).

## Bird's-eye view

```
   ┌──────────────────────────────────── LAPTOP (array processor) ────────────────────────────────────┐
   │                                                                                                 │
   │   ingest (WebSocket)   →   sync (chirp xcorr)   →   TDOA (GCC-PHAT)                               │
   │       │                        │                       │                                        │
   │       ▼                        ▼                       ▼                                        │
   │   ring buffer             aligner (offsets)      radar (position)                              │
   │       │                        │                       │                                        │
   │       └───────────────►  beamform (D&S / MVDR)  ◄─────────────┘                                 │
   │                                │                                                                  │
   │                                ▼                                                                  │
   │                          ASR (interface) → transcript pane                                        │
   │                                │                                                                  │
   │                                ▼                                                                  │
   │                          TTS readback + overlays → screen mirror                                  │
   │                                                                                                 │
   │   metrics (counters/gauges) → :8766 /metrics  → dashboard                                         │
   │   log (JSON or human)         → stderr → shipping                                                 │
   └─────────────────────────────────────────────────────────────────────────────────────────────────┘
        ▲                                                  │
        │ Wi-Fi Direct (Office Kit on iQOO)                │
        │ packets, ~2 KB / 20 ms                           │
   ┌────┴──────────────────────────────────────────┴────────┐
   │  PHONE A (master)        PHONE B (element)   PHONE C  │
   │  foreground capture      foreground capture  …       │
   │  UNPROCESSED @ 48 kHz                             │
   │  chirp beacon every 2 s (master only)              │
   │  heartbeat keep-alive against Funtouch killer      │
   └─────────────────────────────────────────────────────┘
```

## Signal chain (one audio frame, end to end)

```
   1. Capture      2. Frame          3. Stream        4. Align         5. Localise
   UNPROCESSED     30 B header +     WebSocket over   Chirp handshake  TDOA → radar
   @ 48 kHz        PCM + CRC-32C     Wi-Fi Direct     (17.5-22 kHz,     (GCC-PHAT,
   960 int16 /     (Castagnoli,      Office Kit       PRBS sweep,      non-linear
   20 ms          0x1EDC6F41)        bridge           sub-sample xcorr) least-squares)
       │              │                │                  │                │
       └──────────────┴────────────────┴──────────────────┴────────────────┘
                                                                         │
       ┌─────────────────────────────────────────────────────────────────┘
       │
       ▼
   6. Beamform         7. Transcribe       8. Render
   D&S or MVDR         Indic ASR (NPU)     Radar + transcript
   (phase-shift +      QNN-exported        Text-based radar +
   average, or         offline,            live transcript,
   covariance +        on phone A          screen-mirrored
   weights)
```

## Fallback ladder

```
   3-phone live beamform   →   2-phone array     →   single-phone enhance
                                                      (NS + AGC-off)
   Wi-Fi Direct stream     →   chunked file sync →   on-phone-only mode
                             (batch reprocess)
   Ultrasonic sync          →   cable-ping        →   pre-timestamped
                             calibration            exchange

   shruti_array.fallback ingest --corpus <dir> --out <wav>
       └─ Tier-0 batch beamform (D&S or MVDR)
```

## Key numbers (design targets, calibrated on the iQOO loaner fleet)

| Quantity        | Target     | Notes                                        |
|-----------------|------------|----------------------------------------------|
| Sync offset     | < 100 µs   | 42 µs design target; < 100 µs sustained     |
| Sample rate     | 48 kHz     | Mono, 16-bit, all three phones               |
| Frame size      | 20 ms      | 960 samples; beamforming window 80 ms (4 fr) |
| Packet rate     | ~50 pkt/s  | Per phone; rate limit 400 pkt/2 s            |
| CRC             | CRC-32C    | Castagnoli 0x1EDC6F41, iSCSI test 0xE3069283  |
| Latency         | < 200 ms   | Chirp RX → beamformed out, p95               |

## What runs where

```
LAPTOP  (the array processor, the load-bearing use of Office Kit)
  protocol · ingest (WebSocket + /metrics)
  sync (chirp xcorr) · TDOA (GCC-PHAT) · beamform (D&S, MVDR)
  tracker · radar · render (text + judge-facing overlays)
  fallback ladder · regression harness · synthetic corpus · microbenchmark

PHONES  (one master + two elements, foreground services)
  capture (UNPROCESSED, MediaRecorder AudioSource)
  chirp beacon (master)
  heartbeat (keep-alive against Funtouch's background killer)
  transport (TCP/WSS)

PHONE A ALSO RUNS  (because the Snapdragon NPU is the only one available)
  ASR (QNN-exported IndicWhisper / IndicConformer)
  TTS readback (Piper)
```
