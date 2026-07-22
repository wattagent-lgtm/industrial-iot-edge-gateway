"""Bounded Wi-Fi connection and reconnection management."""

import network
import time

import logger
from config import WIFI_SSID, WIFI_PASSWORD, WIFI_CONNECT_TIMEOUT_SECONDS


class WiFiManager:
    def __init__(self):
        self.wlan = network.WLAN(network.STA_IF)

    def is_connected(self):
        return self.wlan.isconnected()

    def connect(self):
        self.wlan.active(True)
        if self.wlan.isconnected():
            return True

        logger.info("Connecting to Wi-Fi: " + WIFI_SSID)
        try:
            self.wlan.disconnect()
        except OSError:
            pass
        self.wlan.connect(WIFI_SSID, WIFI_PASSWORD)

        started = time.ticks_ms()
        timeout_ms = WIFI_CONNECT_TIMEOUT_SECONDS * 1000
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), started) >= timeout_ms:
                logger.warning("Wi-Fi connection timed out")
                return False
            time.sleep_ms(250)

        logger.info("Wi-Fi connected")
        logger.info("Client IP: " + self.ip_address())
        return True

    def ensure_connected(self):
        if self.wlan.isconnected():
            return True
        logger.warning("Wi-Fi disconnected; reconnecting")
        return self.connect()

    def ip_address(self):
        return self.wlan.ifconfig()[0]

