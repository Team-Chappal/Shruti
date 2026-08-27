# Build the laptop processor image.
#
#   docker build -t shruti-laptop:latest .
#
# Run it with both ports exposed:
#
#   docker run --rm -p 8765:8765 -p 8766:8766 shruti-laptop:latest
#
# The metrics endpoint is then at http://localhost:8766/metrics;
# the array processor accepts WebSocket connections on
# ws://localhost:8765. The phones connect to the laptop's
# Wi-Fi-Direct-group IP, not localhost, so the usual docker run
# binds are not directly useful for the demo; in production the
# container runs on the laptop itself with `--network=host`.

FROM python:3.12-slim
