"""Dashboard status payload builders."""

import gc
import network

from config import (GATEWAY_NAME, FIRMWARE_VERSION, TCP_PORT, HTTP_PORT,
                    DASHBOARD_DETAIL_LOG_LIMIT)
from utils import uptime_seconds
from utils import iso_time
from time_manager import synchronized


class DashboardData:
    def __init__(self, tcp, devices, modem=None, mqtt=None):
        self.tcp = tcp
        self.devices = devices
        self.modem = modem
        self.mqtt = mqtt
        self.wlan = network.WLAN(network.STA_IF)

    def status(self, http_running):
        return {
            "gateway_name": GATEWAY_NAME,
            "gateway_status": "RUNNING",
            "uptime_seconds": uptime_seconds(),
            "free_memory": gc.mem_free(),
            "cpu_usage": None,
            "tcp_server": "ONLINE" if self.tcp.running else "OFFLINE",
            "http_server": "ONLINE" if http_running else "OFFLINE",
            "mqtt_status": self.mqtt.state if self.mqtt else "DISABLED",
            "cloud_status": "AWS IOT" if self.mqtt and self.mqtt.connected else "OFFLINE",
            "firmware_version": FIRMWARE_VERSION,
            "system_time": iso_time(),
            "time_synchronized": synchronized(),
            "lte": self.modem.status() if self.modem else {"enabled": False},
            "mqtt": self.mqtt.status() if self.mqtt else {"enabled": False},
        }

    def network(self):
        connected = self.wlan.isconnected()
        config = self.wlan.ifconfig()
        rssi = None
        if connected:
            try:
                rssi = self.wlan.status("rssi")
            except Exception:
                pass
        return {"wifi_status": "CONNECTED" if connected else "DISCONNECTED",
                "wifi_rssi": rssi, "ip_address": config[0], "netmask": config[1],
                "gateway": config[2], "dns": config[3], "tcp_port": TCP_PORT,
                "http_port": HTTP_PORT}

    def statistics(self):
        return {"packets_received": self.tcp.packet_count,
                "packets_per_second": self.tcp.current_rate(),
                "connected_clients": self.tcp.connected_clients,
                "known_devices": self.devices.count(),
                "last_client_ip": self.tcp.last_client_ip,
                "last_json_received": self.tcp.last_json,
                "last_receive_time": self.tcp.last_receive_time}

    def snapshot(self, http_running):
        """Small response for the one-second operational dashboard poll."""
        return {"status": self.status(http_running),
                "network": self.network(),
                "statistics": self.statistics()}

    def details(self, logger):
        """Larger, slow-changing data requested less frequently by the UI."""
        return {"devices": self.devices.list(),
                "logs": logger.entries(DASHBOARD_DETAIL_LOG_LIMIT)}
