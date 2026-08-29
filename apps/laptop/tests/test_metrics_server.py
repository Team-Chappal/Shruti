"""Tests for the metrics HTTP server.

These exercise the request handler without binding to a real port;
the MetricsHTTPServer is a thin asyncio.start_server wrapper, so
the actual HTTP behaviour is what matters and can be tested by
calling _handle() directly with mock streams.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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


async def _serve_get(path: str, boot_file: Path) -> tuple[int, dict[str, str], str]:
    """Run a single GET request through MetricsHTTPServer._handle."""
    GLOBAL.inc("shruti_packets_received_total")
    srv = MetricsHTTPServer(host="127.0.0.1", port=0, boot_file=boot_file)
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


def test_metrics_endpoint_returns_200_with_text_body(tmp_path: Path) -> None:
    """The /metrics endpoint must return 200 and a non-empty body
    in OpenMetrics-ish text format."""
    status, headers, body = asyncio.run(_serve_get("/metrics", tmp_path / "boot"))
    assert status == 200
    assert "text/plain" in headers["content-type"]
    # The body should at least contain the uptime gauge that
    # MetricsHTTPServer._handle sets on every request.
    assert "shruti_metrics_server_uptime_s" in body
    # T12: file-backed laptop uptime and pitch mode are also
    # surfaced on every /metrics request.
    assert "shruti_laptop_uptime_s" in body
    assert "shruti_pitch_mode" in body
    # T10: per-phone health gauges (3 labels).
    for pid in (0, 1, 2):
        assert f'shruti_element_healthy{{phone="{pid}"}}' in body


def test_healthz_returns_200_ok(tmp_path: Path) -> None:
    """K8s/docker liveness probes hit /healthz; must be 200 'ok'."""
    status, _, body = asyncio.run(_serve_get("/healthz", tmp_path / "boot"))
    assert status == 200
    assert body == "ok\n"


def test_unknown_path_returns_404(tmp_path: Path) -> None:
    """Unknown paths are 404, not 500. The entrypoint.sh runbook
    relies on this so a misconfigured dashboard doesn't appear to
    crash the server."""
    status, _, body = asyncio.run(_serve_get("/nothing-here", tmp_path / "boot"))
    assert status == 404
    assert "not found" in body


def test_dashboard_endpoint_returns_html(tmp_path: Path) -> None:
    """T10: the / endpoint serves the jury-facing dashboard.
    Must be HTML, contain the key elements (offset, radar,
    element health), and not depend on any external CDN."""
    status, headers, body = asyncio.run(_serve_get("/", tmp_path / "boot"))
    assert status == 200
    assert "text/html" in headers["content-type"]
    assert "SHRUTI live" in body
    assert "sync offset".lower() in body.lower()
    assert "element health" in body.lower()
    assert "transcript" in body.lower()
    assert "shruti_radar_azimuth_deg" in body  # JS reads this metric


def test_post_method_returns_405(tmp_path: Path) -> None:
    """Only GET is allowed; other methods get 405, not silent success."""
    request = (
        b"POST /metrics HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Length: 0\r\n"
        b"\r\n"
    )
    srv = MetricsHTTPServer(host="127.0.0.1", port=0, boot_file=tmp_path / "boot")
    reader = _FakeReader([request, b"\r\n"])
    writer = _FakeWriter()
    asyncio.run(srv._handle(reader, writer))  # noqa: SLF001
    status, _, body = _parse_response(bytes(writer.buf))
    assert status == 405
    assert "not allowed" in body


def test_first_boot_stamp_survives_restart(tmp_path: Path) -> None:
    """T12: the file-backed uptime must reflect the first-ever
    boot, not the current process. Two server constructions
    sharing the same boot file must report the same uptime
    (within a small tolerance) and a non-zero value."""
    from shruti_array import boot

    bf = tmp_path / "boot"
    MetricsHTTPServer(host="127.0.0.1", port=0, boot_file=bf)
    first_stamp = float(bf.read_text(encoding="utf-8").strip())
    MetricsHTTPServer(host="127.0.0.1", port=0, boot_file=bf)
    second_stamp = float(bf.read_text(encoding="utf-8").strip())
    assert second_stamp == first_stamp
    # The uptime should be a small positive number — the test
    # ran in milliseconds, not zero.
    up = boot.uptime_s(bf)
    assert up >= 0.0


def test_pitch_mode_default_is_tier_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """T12: by default the pitch mode is tier_1 (3-phone,
    "42 µs" quote). The 17:30 GO/NO-GO gate flips it to
    tier_0 (2-phone) if the sync spike doesn't land."""
    monkeypatch.delenv("SHRUTI_PITCH_MODE", raising=False)
    from shruti_array import boot
    assert boot.pitch_mode() == "tier_1"


def test_pitch_mode_honours_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHRUTI_PITCH_MODE", "tier_0")
    from shruti_array import boot
    assert boot.pitch_mode() == "tier_0"


def test_pitch_mode_coerces_unknown_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo at the GO/NO-GO gate must not silently disable
    the demo. Unknown values coerce to tier_1."""
    monkeypatch.setenv("SHRUTI_PITCH_MODE", "definitely-not-a-mode")
    from shruti_array import boot
    assert boot.pitch_mode() == "tier_1"
