"""Stable TCP JSON ingestion service."""

import time
import uasyncio as asyncio

from config import (TCP_PORT, TCP_READ_SIZE, TCP_MAX_MESSAGE_SIZE,
                    TCP_FRAME_TIMEOUT_MS, TCP_CLIENT_IDLE_TIMEOUT_MS)
from utils import parse_json, peer_ip, close_writer, iso_time


ACK = b'{"status":"OK"}'


class TCPServer:
    def __init__(self, devices, logger, mqtt=None):
        self.devices = devices
        self.logger = logger
        self.mqtt = mqtt
        self.server = None
        self.running = False
        self.packet_count = 0
        self.connected_clients = 0
        self.last_client_ip = "None"
        self.last_json = "None"
        self.last_receive_time = "Never"
        self._rate_count = 0
        self._rate_started = time.ticks_ms()
        self.packets_per_second = 0.0

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "0.0.0.0", TCP_PORT)
        self.running = True

    async def handle(self, reader, writer):
        ip = peer_ip(writer)
        self.connected_clients += 1
        try:
            while True:
                data = await self._read_message(reader)
                if not data:
                    break
                payload = data.rstrip(b"\r\n").decode("utf-8")
                parsed = None
                try:
                    parsed = parse_json(payload)
                except (ValueError, UnicodeError):
                    self.logger.warning("Invalid JSON received from %s" % ip)

                # Acknowledge immediately after the bounded frame has been read
                # and JSON validation has completed. Dashboard bookkeeping and
                # cloud queueing must never add latency to the local protocol.
                writer.write(ACK)
                await writer.drain()

                self.packet_count += 1
                self._rate_count += 1
                self._update_rate()
                self.last_client_ip = ip
                self.last_json = payload
                self.last_receive_time = iso_time()
                self.devices.update(ip, payload, parsed)
                if self.mqtt and parsed is not None:
                    # Queue only; never hold the TCP ACK while LTE/AWS is busy.
                    try:
                        self.mqtt.enqueue(payload, parsed)
                    except Exception as exc:
                        # Cloud integration is isolated from the stable local
                        # protocol: an MQTT error must never suppress the ACK.
                        self.logger.warning("MQTT queue: %s" % exc)
        except Exception as exc:
            self.logger.error("TCP client %s: %s" % (ip, exc))
        finally:
            self.connected_clients -= 1
            await close_writer(writer)

    async def _read_message(self, reader):
        """Read one bounded NDJSON frame or a legacy unframed JSON packet.

        Legacy clients wait for an ACK without closing or appending a newline, so a
        short inter-chunk timeout marks the end of those messages. Persistent
        clients may remain idle between newline-delimited frames.
        """
        data = bytearray()
        while len(data) < TCP_MAX_MESSAGE_SIZE:
            remaining = TCP_MAX_MESSAGE_SIZE - len(data)
            read_size = min(TCP_READ_SIZE, remaining)
            timeout_ms = (TCP_CLIENT_IDLE_TIMEOUT_MS if not data
                          else TCP_FRAME_TIMEOUT_MS)
            try:
                chunk = await asyncio.wait_for_ms(
                    reader.read(read_size), timeout_ms)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            data.extend(chunk)
            if b"\n" in chunk:
                frame = bytes(data).split(b"\n", 1)[0]
                return frame
        if len(data) >= TCP_MAX_MESSAGE_SIZE:
            self.logger.warning("TCP message reached %d-byte limit" % TCP_MAX_MESSAGE_SIZE)
        return bytes(data)

    def _update_rate(self):
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self._rate_started)
        if elapsed >= 1000:
            self.packets_per_second = round(self._rate_count * 1000.0 / elapsed, 2)
            self._rate_count = 0
            self._rate_started = now

    def current_rate(self):
        # Do not display a stale non-zero rate after traffic stops.
        if time.ticks_diff(time.ticks_ms(), self._rate_started) >= 2000:
            return 0.0
        return self.packets_per_second
