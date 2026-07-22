"""Small helpers shared by the client modules."""

import time


BOOT_TICKS_MS = time.ticks_ms()


def uptime_ms():
    return time.ticks_diff(time.ticks_ms(), BOOT_TICKS_MS)


def timestamp_or_none():
    """NTP/RTC support can replace this later; never invent wall-clock time."""
    return None


def sleep_until(target_ticks_ms):
    """Sleep toward a ticks_ms deadline without long blocking sleeps."""
    while True:
        remaining = time.ticks_diff(target_ticks_ms, time.ticks_ms())
        if remaining <= 0:
            return
        time.sleep_ms(min(remaining, 100))

