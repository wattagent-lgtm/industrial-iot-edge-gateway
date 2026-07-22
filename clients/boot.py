"""MicroPython boot hook: initialize Wi-Fi only."""

import gc

from wifi_manager import WiFiManager


wifi = WiFiManager()
wifi.connect()
gc.collect()

