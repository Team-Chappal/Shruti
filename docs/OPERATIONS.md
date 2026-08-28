# SHRUTI — Operations runbook

How to run, monitor, and recover the laptop processor in the demo
venue. The Android side has its own runbook embedded in the source
(see `NEEDS-DEVICE` markers); this document covers the laptop.

## Starting the processor

The default command runs the array processor with sensible defaults:

```sh
shruti-array run-radar
```

To override the host or port:

```sh
shruti-array run-radar --host 192.168.49.1 --port 8765
```

In a separate terminal, start the metrics HTTP server so the
dashboard can scrape it:

```sh
python -m shruti_array.ingest.metrics_server --port 8766
```

## Generating the synthetic corpus (smoke test)

The synthetic suite is what CI runs and what to run before the
event to confirm the DSP is still alive:

```sh
cd apps/laptop
make synth         # writes 5 deterministic scenes to data/corpus/synth/
make harness      # runs the regression, writes data/regression_runs/report.json
```

## Running the regression manually

```sh
shruti-array harness \
    --scenes 5 \
    --duration-s 2.0 \
    --out data/regression_runs/report.json \
    --require-mvdr-gain-db 0.0
```

`--require-mvdr-gain-db` is the pass/fail gate: MVDR must beat
delay-and-sum by at least this many dB on average. The default 0.0
means "MVDR must not be worse" (a smoke gate). For the event gate,
set it to 3.0 and ensure you're running on the recorded corpus.

## Monitoring the live demo

The metrics endpoint exposes:

- `shruti_packets_received_total` — total packets from all phones
- `shruti_packets_decoded_total` — packets that passed CRC
- `shruti_packets_rejected_total` — packets rejected (size, CRC,
  rate limit)
- `shruti_crc_failures_total` — CRC mismatches
- `shruti_dropped_frames_total` — sequence gaps
- `shruti_active_phones` — phones currently connected
- `shruti_sync_offset_microseconds` — last measured sync offset
- `shruti_sync_stability_microseconds` — std dev of the offset
- `shruti_uptime_s` — how long the processor has been running

A healthy demo shows:

- `shruti_active_phones = 3`
- `shruti_crc_failures_total` growing at < 0.1% of
  `shruti_packets_received_total`
- `shruti_sync_stability_microseconds < 100`
- `shruti_dropped_frames_total = 0` (modulo brief spikes during
  chirp re-syncs)

Scrape with:

```sh
curl http://localhost:8766/metrics
```

## Restarting cleanly

If the processor is in a bad state (e.g., a runaway phone wedged
the queue), the cleanest recovery is to restart it. Phones will
reconnect automatically; the chirp handshake will re-establish
sync within 2 seconds of the master phone's next heartbeat.

```sh
# Find the process and kill it (Ctrl-C in the foreground, or):
pkill -f "shruti-array run-radar"
# Then restart:
shruti-array run-radar
```

## Switching to the fallback ladder

The fallback ladder (live stream -> batch file -> red-light) is
driven manually. The triggers are described in
`tools/rebuild/recipe.md` step 6.

To pull WAV files from a phone over `adb` (batch rung):

```sh
adb -s <phone> pull /sdcard/shruti/captures/ data/corpus/recorded/<scene>/
```

To run the batch mode against a directory:

```sh
python -m shruti_array.fallback ingest \
    --corpus data/corpus/recorded/<scene>/ \
    --out /tmp/beamformed.wav
# or, for the recorded-corpus event gate:
python -m shruti_array.fallback ingest \
    --corpus data/corpus/recorded/<scene>/ \
    --out /tmp/beamformed.wav \
    --beamform mvdr
```

The CLI accepts two filename conventions: `<phone_id>_<...>.wav`
(recorded corpus) and `ch<phone_id>.wav` (synthetic corpus). See
`python -m shruti_array.fallback --help` for the `ingest`, `ls`,
and `next` subcommands.

## Logs

By default, logs are human-readable on stderr. For machine
ingestion, set `SHRUTI_LOG_FORMAT=json`:

```sh
SHRUTI_LOG_FORMAT=json shruti-array run-radar
```

## Backing up the run

The laptop processor is stateless. Nothing to back up during a
run. The recorded corpus and the regression report are the only
artifacts worth keeping; both live under `data/`.
