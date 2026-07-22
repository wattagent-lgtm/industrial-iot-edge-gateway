"""Bounded registry of devices observed on the TCP service."""

from config import DEVICE_CAPACITY
from utils import iso_time


class DeviceManager:
    def __init__(self, logger, capacity=DEVICE_CAPACITY):
        self.logger = logger
        self.capacity = capacity
        self._devices = {}

    def update(self, ip, payload, parsed=None):
        # Versioned plug-and-play clients use device_id. Keep the original
        # node_id/id/IP fallbacks for full backward compatibility.
        node_id = self._field(parsed, "device_id",
                              self._field(parsed, "node_id",
                                          self._field(parsed, "id", ip)))
        node_id = str(node_id)
        name = self._field(parsed, "device_name", self._field(parsed, "name", node_id))
        device = self._devices.get(node_id)

        if device is None:
            if len(self._devices) >= self.capacity:
                self._evict_oldest()
            device = {"device_name": str(name), "node_id": node_id,
                      "ip_address": ip, "last_seen": "", "packet_count": 0,
                      "latest_json": ""}
            self._devices[node_id] = device
            self.logger.info("Device discovered: %s (%s)" % (node_id, ip))

        device["device_name"] = str(name)
        device["ip_address"] = ip
        device["last_seen"] = iso_time()
        device["packet_count"] += 1
        device["latest_json"] = payload

    @staticmethod
    def _field(value, key, default):
        return value.get(key, default) if isinstance(value, dict) else default

    def _evict_oldest(self):
        oldest_key = None
        oldest_seen = None
        for key, value in self._devices.items():
            seen = value["last_seen"]
            if oldest_seen is None or seen < oldest_seen:
                oldest_key, oldest_seen = key, seen
        if oldest_key is not None:
            del self._devices[oldest_key]

    def list(self):
        return list(self._devices.values())

    def count(self):
        return len(self._devices)
