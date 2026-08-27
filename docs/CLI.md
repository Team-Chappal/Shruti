# SHRUTI — CLI reference

The laptop processor ships with a single CLI entry point,
`shruti-array`, and a few module-level CLIs for the tools.

## `shruti-array`

```
shruti-array [-h] {run-radar,synth-corpus,harness,audit} ...
```

### `run-radar`

Start the array processor. Accepts WebSocket connections from the
phones, runs the DSP loop, and (optionally) renders the radar UI.

```
shruti-array run-radar [--host HOST] [--port PORT]
```

Defaults: `--host 0.0.0.0`, `--port 8765`.

### `synth-corpus`

Generate a deterministic synthetic scene suite under
`data/corpus/synth/`. Useful as a smoke test and as a reproducible
input to the regression harness.

```
shruti-array synth-corpus
```

(Underlying tool: `python -m shruti_array.tools.corpus synth
--out data/corpus/synth`.)

### `harness`

Run the regression suite and emit a JSON report.

```
shruti-array harness
    [--scenes N]               # default 5
    [--duration-s S]          # default 2.0
    [--out PATH]              # default data/regression_runs/report.json
    [--require-mvdr-gain-db D] # pass/fail threshold; default 0.0
```

Exit code 0 if the average MVDR gain ≥ threshold; 1 otherwise.

### `audit`

Analyze a directory of per-phone WAV captures and write a
characterization report (RMS, peak, noise floor, sample rate,
duration per phone).

```
shruti-array audit
    [--captures DIR]   # default data/captures
    [--out PATH]       # default data/audit/report.json
```

## Module-level CLIs

### `python -m shruti_array.tools.corpus`

`corpus synth --out DIR [--scenes N] [--duration-s S]`
generates a synthetic scene suite.

`corpus record` is reserved for the future live-recording tool;
the team currently uses `tools/record_corpus.py` to scaffold
real-corpus scene directories.

### `python -m shruti_array.harness.regression`

Same as `shruti-array harness`.

### `python -m shruti_array.tools.audit`

Same as `shruti-array audit`.

### `python -m shruti_array.ingest.metrics_server`

Start the standalone `/metrics` HTTP server on a separate port.

```
python -m shruti_array.ingest.metrics_server --host 0.0.0.0 --port 8766
```

### `python -m shruti_array.tools.record_corpus`

Scaffold a real-corpus scene directory (see
`tools/record_corpus.md` for the workflow).

```
python -m tools.record_corpus \
    --out data/corpus/recorded/<scene> \
    --name <scene-name> \
    --room <room-name> \
    --target-azimuth-deg 20 \
    --interferer-azimuth-deg -45 \
    --duration-s 60
```

## Environment variables

- `SHRUTI_LOG_FORMAT` — set to `json` for machine-readable logs;
  default is human-readable.
- `PYTHONPATH` — must include `apps/laptop/` if running
  `python -m shruti_array.*` from outside that directory.
