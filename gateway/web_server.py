"""Minimal async HTTP/1.1 server and REST API for MicroPython."""

import gc
import machine
import uasyncio as asyncio

from config import (HTTP_PORT, HTTP_READ_SIZE, STATIC_ROOT,
                    HTTP_GC_INTERVAL_REQUESTS, HTTP_GC_LOW_MEMORY_BYTES,
                    HTTP_MAX_ACTIVE_REQUESTS)
from dashboard import DashboardData
from utils import json_dumps, close_writer


CONTENT_TYPES = {"html": "text/html; charset=utf-8", "css": "text/css",
                 "js": "application/javascript", "svg": "image/svg+xml"}
STATUS_REASONS = {200: "OK", 202: "Accepted", 400: "Bad Request",
                  404: "Not Found", 405: "Method Not Allowed",
                  500: "Internal Server Error", 503: "Service Unavailable"}


class WebServer:
    def __init__(self, tcp, devices, logger, modem=None, mqtt=None):
        self.tcp = tcp
        self.devices = devices
        self.logger = logger
        self.dashboard = DashboardData(tcp, devices, modem, mqtt)
        self.server = None
        self.running = False
        self._requests_since_gc = 0
        self.active_requests = 0
        self.rejected_requests = 0
        self.restart_count = 0

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "0.0.0.0", HTTP_PORT)
        self.running = True

    async def restart(self):
        self.running = False
        old_server = self.server
        self.server = None
        if old_server:
            try:
                old_server.close()
            except Exception:
                pass
            try:
                wait_closed = getattr(old_server, "wait_closed", None)
                if wait_closed:
                    await asyncio.wait_for_ms(wait_closed(), 1000)
            except Exception:
                pass
        await asyncio.sleep_ms(250)
        gc.collect()
        await self.start()
        self.restart_count += 1
        self.logger.warning("HTTP server recovered by supervisor")

    async def handle(self, reader, writer):
        if self.active_requests >= HTTP_MAX_ACTIVE_REQUESTS:
            self.rejected_requests += 1
            await close_writer(writer)
            return
        self.active_requests += 1
        try:
            request = await reader.read(HTTP_READ_SIZE)
            if not request:
                return
            first = request.split(b"\r\n", 1)[0].decode("utf-8")
            parts = first.split(" ")
            if len(parts) < 2:
                await self._json(writer, 400, {"error": "bad request"})
                return
            method, path = parts[0], parts[1].split("?", 1)[0]
            await self._route(writer, method, path)
        except OSError as exc:
            # Browsers routinely cancel superseded polling connections. This is not
            # a gateway fault and must not consume the bounded log buffer.
            error_number = exc.args[0] if exc.args else None
            if error_number not in (104, 128):
                self.logger.error("HTTP request: %s" % exc)
                try:
                    await self._json(writer, 500, {"error": "internal server error"})
                except Exception:
                    pass
        except Exception as exc:
            self.logger.error("HTTP request: %s" % exc)
            try:
                await self._json(writer, 500, {"error": "internal server error"})
            except Exception:
                pass
        finally:
            await close_writer(writer)
            self.active_requests -= 1
            # A full collection after every one-second dashboard poll wastes CPU.
            # Collect periodically, or immediately if the heap is under pressure.
            self._requests_since_gc += 1
            if (self._requests_since_gc >= HTTP_GC_INTERVAL_REQUESTS or
                    gc.mem_free() < HTTP_GC_LOW_MEMORY_BYTES):
                gc.collect()
                self._requests_since_gc = 0

    async def _route(self, writer, method, path):
        if method == "GET" and path == "/api/health":
            return await self._json(writer, 200, {
                "status": "OK", "active_requests": self.active_requests,
                "rejected_requests": self.rejected_requests,
                "restart_count": self.restart_count,
                "free_memory_bytes": gc.mem_free()})
        if method == "GET" and path == "/api/snapshot":
            return await self._json(writer, 200,
                                    self.dashboard.snapshot(self.running))
        if method == "GET" and path == "/api/details":
            return await self._json(writer, 200,
                                    self.dashboard.details(self.logger))
        if method == "GET" and path == "/api/status":
            return await self._json(writer, 200, self.dashboard.status(self.running))
        if method == "GET" and path == "/api/network":
            return await self._json(writer, 200, self.dashboard.network())
        if method == "GET" and path == "/api/statistics":
            return await self._json(writer, 200, self.dashboard.statistics())
        if method == "GET" and path == "/api/devices":
            return await self._json(writer, 200, {"devices": self.devices.list()})
        if method == "GET" and path == "/api/logs":
            return await self._json(writer, 200, {"logs": self.logger.entries(50)})
        if method == "POST" and path == "/api/restart":
            self.logger.warning("Restart requested from dashboard")
            await self._json(writer, 202, {"status": "restarting"})
            await asyncio.sleep_ms(250)
            machine.reset()
            return
        if method == "POST" and path == "/api/lte/test":
            if not self.dashboard.modem:
                return await self._json(writer, 503, {"error": "LTE modem disabled"})
            started = self.dashboard.modem.start_internet_test()
            return await self._json(writer, 202,
                                    {"status": "testing" if started else "already_running"})
        if method != "GET":
            return await self._json(writer, 405, {"error": "method not allowed"})
        if path == "/":
            path = "/index.html"
        if path in ("/index.html", "/style.css", "/app.js", "/logo.svg"):
            return await self._file(writer, STATIC_ROOT + path)
        await self._json(writer, 404, {"error": "not found"})

    async def _json(self, writer, status, value):
        body = json_dumps(value).encode("utf-8")
        await self._response(writer, status, "application/json", body)

    async def _file(self, writer, path):
        try:
            size = __import__("os").stat(path)[6]
            ext = path.rsplit(".", 1)[-1]
            await self._headers(writer, 200, CONTENT_TYPES.get(ext, "application/octet-stream"), size)
            with open(path, "rb") as source:
                while True:
                    chunk = source.read(512)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
        except OSError:
            await self._json(writer, 404, {"error": "file not found"})

    async def _response(self, writer, status, content_type, body):
        await self._headers(writer, status, content_type, len(body))
        writer.write(body)
        await writer.drain()

    async def _headers(self, writer, status, content_type, length):
        # Reuse the module-level table instead of allocating a dictionary for
        # every one-second dashboard response.
        reason = STATUS_REASONS.get(status, "OK")
        header = ("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                  "Cache-Control: no-cache\r\nConnection: close\r\n\r\n") % (
                      status, reason, content_type, length)
        writer.write(header.encode("utf-8"))
        await writer.drain()
