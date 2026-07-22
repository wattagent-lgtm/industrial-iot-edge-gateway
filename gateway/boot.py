"""MicroPython boot hook: bring up the station interface before main.py."""

import time
import network
from config import (WIFI_SSID, WIFI_PASSWORD, WIFI_TIMEOUT_SECONDS,
                    WIFI_STATIC_IP_ENABLED, WIFI_STATIC_IP, WIFI_NETMASK,
                    WIFI_GATEWAY, WIFI_DNS, WEBREPL_ENABLED,
                    WEBREPL_PASSWORD, NTP_ENABLED)


wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if WIFI_STATIC_IP_ENABLED:
    try:
        wlan.ifconfig((WIFI_STATIC_IP, WIFI_NETMASK, WIFI_GATEWAY, WIFI_DNS))
        print("Configured static IP:", WIFI_STATIC_IP)
    except Exception as exc:
        # Do not prevent boot on ports that reject static configuration.
        print("Static IP configuration failed; using DHCP:", exc)

if not wlan.isconnected():
    print("Connecting to", WIFI_SSID)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    started = time.ticks_ms()
    timeout_ms = WIFI_TIMEOUT_SECONDS * 1000
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), started) >= timeout_ms:
            print("WiFi connection timed out")
            break
        time.sleep_ms(250)

print("Network:", wlan.ifconfig())

if WEBREPL_ENABLED and wlan.isconnected():
    try:
        import webrepl
        webrepl.start(password=WEBREPL_PASSWORD)
        print("WebREPL enabled on ws://%s:8266" % wlan.ifconfig()[0])
    except ImportError:
        print("WebREPL module is not included in this MicroPython firmware")
    except Exception as exc:
        print("WebREPL failed:", exc)

if NTP_ENABLED and wlan.isconnected():
    from time_manager import sync_time
    sync_time()
