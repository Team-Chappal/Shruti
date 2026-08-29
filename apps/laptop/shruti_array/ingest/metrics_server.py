"""Tiny HTTP server that exposes /metrics, /healthz, and a /
dashboard page (T10 + T12).

Runs on a different port from the WebSocket server so the two
transports stay cleanly separated. The webserver is hand-rolled on
top of `asyncio.start_server` to avoid pulling in a full ASGI
framework; the request volume is one scrape every few seconds, so
the simplicity wins.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path

from .. import boot
from ..log import get_logger
from ..metrics import GLOBAL as METRICS
from .websocket_server import PacketServer

log = get_logger(__name__)


MetricsHandler = Callable[["MetricsRequest"], None]


class MetricsRequest:
    __slots__ = ("path", "response", "_done")

    def __init__(self, path: str) -> None:
        self.path = path
        self.response: tuple[int, dict[str, str], bytes] | None = None
        self._done = False

    def send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        if self._done:
            return
        self._done = True
        self.response = (status, {"Content-Type": content_type, "Cache-Control": "no-store"}, body)


def _render(payload: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> bytes:
    return f"HTTP/1.1 {status} OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n{payload}".encode("latin-1")


def _load_dashboard_html() -> bytes:
    """Read the dashboard HTML once at server-start time. The
    file is a sibling of this module; we resolve relative to
    __file__ so the asset works no matter where the package
    is installed from."""
    here = Path(__file__).resolve().parent
    path = here / "dashboard.html"
    return path.read_bytes()


class MetricsHTTPServer:
    # The default 0.0.0.0 bind is intentional: the metrics
    # endpoint must be reachable from the same Wi-Fi Direct
    # group as the phones, on the same network as the
    # dashboard scraper. See ServerConfig above for the
    # trust-model rationale.
    def __init__(
        self,
        host: str = "0.0.0.0",  # nosec B104 — intentional, see ServerConfig
        port: int = 8766,
        packet_server: PacketServer | None = None,
        boot_file: Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.packet_server = packet_server
        # T12: stamp the boot time on first start. If the
        # stamp file already exists, leave it alone — that's
        # the laptop's first-ever boot, which is what the
        # "uptime, all night" line refers to.
        self._boot_file = boot_file or boot.DEFAULT_BOOT_FILE
        boot.mark_boot(self._boot_file)
        self._dashboard_html: bytes = _load_dashboard_html()

    async def start(self) -> None:
        log.info("metrics HTTP server listening on http://%s:%d/ (dashboard)", self.host, self.port)
        async with await asyncio.start_server(self._handle, host=self.host, port=self.port) as srv:
            await srv.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        except (asyncio.TimeoutError, ConnectionResetError):
            writer.close()
            return
        if not request_line:
            writer.close()
            return
        try:
            method, path, _ = request_line.decode("latin-1").split(" ", 2)
        except ValueError:
            return
        # Drain headers.
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"", b"\n"):
                break
        if method != "GET":
            writer.write(_render("method not allowed\n", status=405))
            await writer.drain()
            writer.close()
            return

        # Refresh the dashboard's metrics every request. Cheap,
        # and guarantees the polled /metrics text reflects the
        # current state, not a stale gauge.
        self._refresh_dashboard_gauges()

        if path.startswith("/metrics"):
            body = METRICS.render().encode("utf-8")
            writer.write(_render(body.decode("utf-8"), content_type="text/plain; version=0.0.4; charset=utf-8"))
        elif path.startswith("/healthz"):
            writer.write(_render("ok\n"))
        elif path == "/" or path.startswith("/index"):
            # T10: the live dashboard. Single-page, polls
            # /metrics every 2 s, no install on the display
            # device — just point a browser at the laptop.
            writer.write(
                _render(
                    self._dashboard_html.decode("utf-8"),
                    content_type="text/html; charset=utf-8",
                )
            )
        else:
            writer.write(_render("not found\n", status=404))
        await writer.drain()
        writer.close()

    def _refresh_dashboard_gauges(self) -> None:
        """Push the gauges the dashboard JS reads."""
        # T12: file-backed uptime, NOT the per-process uptime.
        up = boot.uptime_s(self._boot_file)
        METRICS.set_gauge("shruti_laptop_uptime_s", up)
        # T12: pitch-mode flag. 1 = tier_1, 0 = tier_0.
        METRICS.set_gauge(
            "shruti_pitch_mode",
            1.0 if boot.pitch_mode() == boot.PITCH_MODE_TIER_1 else 0.0,
        )
        METRICS.set_gauge("shruti_metrics_server_uptime_s", time.time() - os.stat(self._boot_file).st_mtime + up)
        if self.packet_server is not None:
            phones = self.packet_server.all_phone_ids()
        else:
            # T10: even with no packet_server attached, surface
            # the three element_healthy gauges as 0 so the
            # dashboard renders three red dots (not "no data").
            # This is the right default for a laptop booted
            # before any phone has connected.
            phones = []
        METRICS.set_gauge("shruti_active_phones", len(phones))
        # T10: per-phone health dot. The packet_server knows
        # who's connected; we surface it as a labelled gauge so
        # the dashboard can render Phone 0 / Phone 1 / Phone 2
        # as a row of green/red dots. Always surface 3 labels.
        for pid in range(3):
            METRICS.set_gauge(
                "shruti_element_healthy",
                1.0 if pid in phones else 0.0,
                phone=str(pid),
            )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point so `python -m shruti_array.ingest.metrics_server`
    works (used by the Dockerfile's entrypoint.sh and the OPERATIONS.md
    runbook)."""
    import argparse

    p = argparse.ArgumentParser(
        description="SHRUTI metrics HTTP server. Exposes /metrics "
        "(OpenMetrics text), /healthz, and a / dashboard page "
        "for the jury-facing readout.",
    )
    p.add_argument("--host", default="0.0.0.0", help="Bind address (default 0.0.0.0, see ServerConfig)")  # nosec B104
    p.add_argument("--port", type=int, default=8766, help="Bind port (default 8766)")
    args = p.parse_args(argv)

    server = MetricsHTTPServer(host=args.host, port=args.port)
    asyncio.run(server.start())
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
