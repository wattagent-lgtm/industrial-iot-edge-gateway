"""Run the finite pump telemetry simulation."""

import gc
import time

import logger
import simulator
from config import (GATEWAY_IP, GATEWAY_PORT, NODE_ID, DEVICE_NAME,
                    DEVICE_TYPE, SITE, AREA, LINE, SEND_INTERVAL_SECONDS,
                    SIMULATION_DURATION_SECONDS, SCHEMA_VERSION)
from tcp_client import TCPClient
from utils import uptime_ms, timestamp_or_none, sleep_until
from wifi_manager import WiFiManager


def build_message(sequence, telemetry):
    return {
        "schema_version": SCHEMA_VERSION,
        "message_type": "telemetry",
        "node_id": NODE_ID,
        "device_name": DEVICE_NAME,
        "device_type": DEVICE_TYPE,
        "site": SITE,
        "area": AREA,
        "line": LINE,
        "seq": sequence,
        "uptime_ms": uptime_ms(),
        "timestamp": timestamp_or_none(),
        "status": simulator.status_for(telemetry),
        "data": telemetry,
    }


def run():
    wifi = WiFiManager()
    wifi.ensure_connected()
    logger.info("Client IP: " + wifi.ip_address() if wifi.is_connected() else "Client IP: unavailable")
    logger.info("Gateway: %s:%d" % (GATEWAY_IP, GATEWAY_PORT))

    client = TCPClient(wifi)
    planned = SIMULATION_DURATION_SECONDS // SEND_INTERVAL_SECONDS
    acknowledged = 0
    failed = 0
    started = time.ticks_ms()
    interval_ms = SEND_INTERVAL_SECONDS * 1000

    for sequence in range(1, planned + 1):
        # First sample is sent immediately; later samples retain the 3-second cadence.
        sleep_until(time.ticks_add(started, (sequence - 1) * interval_ms))
        logger.info("Sending packet %d/%d" % (sequence, planned))
        message = build_message(sequence, simulator.read_telemetry())

        if client.send_with_retry(message):
            acknowledged += 1
        else:
            failed += 1
            logger.error("Packet %d failed after retry" % sequence)
        gc.collect()

    # Keep the finite run at least the configured duration when sends finish early.
    sleep_until(time.ticks_add(started, SIMULATION_DURATION_SECONDS * 1000))
    elapsed = time.ticks_diff(time.ticks_ms(), started) // 1000
    logger.info("Packets planned: %d" % planned)
    logger.info("Packets acknowledged: %d" % acknowledged)
    logger.info("Packets failed: %d" % failed)
    logger.info("Simulation duration: %d seconds" % elapsed)
    logger.info("Simulation Complete")


run()
