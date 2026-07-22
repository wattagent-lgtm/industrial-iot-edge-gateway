"""Gateway service coordinator.

This module intentionally retains start_gateway() as the public entry point used
by the original main.py deployment.
"""

import gc
import network
import uasyncio as asyncio

from config import (TCP_PORT, HTTP_PORT, MODEM_ENABLED, MQTT_ENABLED,
                    WIFI_SSID, WIFI_PASSWORD,
                    WIFI_STATIC_IP_ENABLED, WIFI_STATIC_IP, WIFI_NETMASK,
                    WIFI_GATEWAY, WIFI_DNS,
                    WIFI_MONITOR_INTERVAL_SECONDS,
                    WIFI_RECONNECT_TIMEOUT_SECONDS,
                    HTTP_HEALTH_INTERVAL_SECONDS,
                    HTTP_HEALTH_FAILURE_LIMIT, HTTP_HEALTH_TIMEOUT_MS)
from device_manager import DeviceManager
from logger import GatewayLogger
from tcp_server import TCPServer
from web_server import WebServer
from modem_manager import ModemManager
from mqtt_manager import MQTTManager
from utils import close_writer


async def _http_probe(ip):
    reader = None
    writer = None
    try:
        reader, writer = await asyncio.wait_for_ms(
            asyncio.open_connection(ip, HTTP_PORT), HTTP_HEALTH_TIMEOUT_MS)
        writer.write(b"GET /api/health HTTP/1.1\r\nConnection: close\r\n\r\n")
        await asyncio.wait_for_ms(writer.drain(), HTTP_HEALTH_TIMEOUT_MS)
        response = await asyncio.wait_for_ms(reader.read(48),
                                             HTTP_HEALTH_TIMEOUT_MS)
        return response.startswith(b"HTTP/1.1 200")
    except Exception:
        return False
    finally:
        if writer:
            await close_writer(writer)


async def _recover_wifi(wlan, log):
    log.warning("WiFi disconnected; attempting recovery")
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
        await asyncio.sleep(1)
        wlan.active(True)
        if WIFI_STATIC_IP_ENABLED:
            wlan.ifconfig((WIFI_STATIC_IP, WIFI_NETMASK,
                           WIFI_GATEWAY, WIFI_DNS))
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        waited = 0
        while not wlan.isconnected() and waited < WIFI_RECONNECT_TIMEOUT_SECONDS:
            await asyncio.sleep(1)
            waited += 1
        if wlan.isconnected():
            log.info("WiFi recovered: " + wlan.ifconfig()[0])
            return True
    except Exception as exc:
        log.error("WiFi recovery: %s" % exc)
    return False


async def _service_supervisor(wlan, web, log):
    http_failures = 0
    elapsed = HTTP_HEALTH_INTERVAL_SECONDS
    while True:
        if not wlan.isconnected():
            if await _recover_wifi(wlan, log):
                try:
                    await web.restart()
                    http_failures = 0
                except Exception as exc:
                    log.error("HTTP restart after WiFi recovery: %s" % exc)
            await asyncio.sleep(WIFI_MONITOR_INTERVAL_SECONDS)
            continue

        elapsed += WIFI_MONITOR_INTERVAL_SECONDS
        if elapsed >= HTTP_HEALTH_INTERVAL_SECONDS:
            elapsed = 0
            ip = wlan.ifconfig()[0]
            if await _http_probe(ip):
                http_failures = 0
            else:
                http_failures += 1
                if http_failures >= HTTP_HEALTH_FAILURE_LIMIT:
                    log.warning("HTTP health check failed; restarting server")
                    try:
                        await web.restart()
                        http_failures = 0
                    except Exception as exc:
                        log.error("HTTP supervisor: %s" % exc)
        await asyncio.sleep(WIFI_MONITOR_INTERVAL_SECONDS)


async def start_gateway():
    log = GatewayLogger()
    devices = DeviceManager(log)
    modem = ModemManager(log) if MODEM_ENABLED else None
    mqtt = MQTTManager(modem, log) if modem and MQTT_ENABLED else None
    tcp = TCPServer(devices, log, mqtt)
    web = WebServer(tcp, devices, log, modem, mqtt)

    await tcp.start()
    await web.start()
    if modem:
        asyncio.create_task(modem.start())
    if mqtt:
        asyncio.create_task(mqtt.start())

    wlan = network.WLAN(network.STA_IF)
    asyncio.create_task(_service_supervisor(wlan, web, log))

    ip = wlan.ifconfig()[0]
    log.info("TCP server listening on port %d" % TCP_PORT)
    log.info("HTTP dashboard available at http://%s:%d" % (ip, HTTP_PORT))
    print("TCP:", TCP_PORT)
    print("WEB:http://" + ip)

    memory_warning_active = False
    while True:
        gc.collect()
        free_memory = gc.mem_free()
        if free_memory < 45000:
            # Preserve recent diagnostics while releasing older log strings.
            log.trim(25)
            gc.collect()
            if not memory_warning_active:
                log.warning("Critical heap pressure; old logs released")
                memory_warning_active = True
        elif free_memory < 55000:
            if not memory_warning_active:
                log.warning("Low heap memory: %d bytes" % free_memory)
                memory_warning_active = True
        else:
            memory_warning_active = False
        await asyncio.sleep(10)
