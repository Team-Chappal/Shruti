"""Tiny HTTP server that exposes /metrics and /healthz.

Runs on a different port from the WebSocket server so the two
transports stay cleanly separated. The webserver is hand-rolled on
top of `asyncio.start_server` to avoid pulling in a full ASGI
framework; the request volume is one scrape every few seconds, so
the simplicity wins.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

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


class MetricsHTTPServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8766, packet_server: PacketServer | None = None) -> None:
        self.host = host
        self.port = port
        self.packet_server = packet_server
        self._started_at = time.time()

    async def start(self) -> None:
        log.info("metrics HTTP server listening on http://%s:%d/metrics", self.host, self.port)
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

        uptime = time.time() - self._started_at
        METRICS.set_gauge("shruti_metrics_server_uptime_s", uptime)
        if self.packet_server is not None:
            METRICS.set_gauge("shruti_active_phones", len(self.packet_server.all_phone_ids()))

        if path.startswith("/metrics"):
            body = METRICS.render().encode("utf-8")
            writer.write(_render(body.decode("utf-8"), content_type="text/plain; version=0.0.4; charset=utf-8"))
        elif path.startswith("/healthz"):
            writer.write(_render("ok\n"))
        else:
            writer.write(_render("not found\n", status=404))
        await writer.drain()
        writer.close()
