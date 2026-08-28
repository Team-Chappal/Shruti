"""Tests for the metrics HTTP server.

These exercise the request handler without binding to a real port;
the MetricsHTTPServer is a thin asyncio.start_server wrapper, so
the actual HTTP behaviour is what matters and can be tested by
calling _handle() directly with mock streams.
"""
from __future__ import annotations

import asyncio

from shruti_array.ingest.metrics_server import MetricsHTTPServer
from shruti_array.metrics import GLOBAL


class _FakeReader:
    """Minimal stand-in for asyncio.StreamReader."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeWriter:
    """Collects the bytes written so tests can assert on the response."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buf.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def _parse_response(raw: bytes) -> tuple[int, dict[str, str], str]:
    """Parse a minimal HTTP/1.1 response into (status, headers, body)."""
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = int(lines[0].split(b" ")[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        k, _, v = line.partition(b":")
        headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
    return status, headers, body.decode("utf-8", errors="replace")


async def _serve_get(path: str) -> tuple[int, dict[str, str], str]:
    """Run a single GET request through MetricsHTTPServer._handle."""
    GLOBAL.inc("shruti_packets_received_total")
    srv = MetricsHTTPServer(host="127.0.0.1", port=0)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: 127.0.0.1\r\n"
        f"User-Agent: test\r\n"
        f"\r\n"
    )
    reader = _FakeReader([request.encode("latin-1"), b"\r\n"])
    writer = _FakeWriter()
    await srv._handle(reader, writer)  # noqa: SLF001
    return _parse_response(bytes(writer.buf))


def test_metrics_endpoint_returns_200_with_text_body() -> None:
    """The /metrics endpoint must return 200 and a non-empty body
    in OpenMetrics-ish text format."""
    status, headers, body = asyncio.run(_serve_get("/metrics"))
    assert status == 200
    assert "text/plain" in headers["content-type"]
    # The body should at least contain the uptime gauge that
    # MetricsHTTPServer._handle sets on every request.
    assert "shruti_metrics_server_uptime_s" in body


def test_healthz_returns_200_ok() -> None:
    """K8s/docker liveness probes hit /healthz; must be 200 'ok'."""
    status, _, body = asyncio.run(_serve_get("/healthz"))
    assert status == 200
    assert body == "ok\n"


def test_unknown_path_returns_404() -> None:
    """Unknown paths are 404, not 500. The entrypoint.sh runbook
    relies on this so a misconfigured dashboard doesn't appear to
    crash the server."""
    status, _, body = asyncio.run(_serve_get("/nothing-here"))
    assert status == 404
    assert "not found" in body


def test_post_method_returns_405() -> None:
    """Only GET is allowed; other methods get 405, not silent success."""
    request = (
        b"POST /metrics HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Length: 0\r\n"
        b"\r\n"
    )
    srv = MetricsHTTPServer(host="127.0.0.1", port=0)
    reader = _FakeReader([request, b"\r\n"])
    writer = _FakeWriter()
    asyncio.run(srv._handle(reader, writer))  # noqa: SLF001
    status, _, body = _parse_response(bytes(writer.buf))
    assert status == 405
    assert "not allowed" in body
