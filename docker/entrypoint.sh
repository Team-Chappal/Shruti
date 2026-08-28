#!/bin/sh
# Entry point for the SHRUTI laptop processor container.
# Starts the metrics HTTP server and the array processor in the
# foreground so Docker can supervise both as one process.
set -eu

# Start the metrics server in the background. It binds 0.0.0.0:8766.
python -m shruti_array.ingest.metrics_server --host 0.0.0.0 --port 8766 &
METRICS_PID=$!

# Trap signals so the metrics server dies when the array processor
# is stopped (e.g. via `docker stop`).
trap "kill $METRICS_PID 2>/dev/null || true" EXIT INT TERM

# Run the array processor in the foreground. All CLI args are
# forwarded; default is `run-radar` on 0.0.0.0:8765.
exec python -m shruti_array.cli "$@"
