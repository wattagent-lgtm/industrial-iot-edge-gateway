"""Fault-tolerant NTP synchronization for the gateway RTC."""

import time

from config import NTP_HOST, NTP_RETRIES, NTP_RETRY_DELAY_SECONDS


_synchronized = False
_last_error = None


def is_time_valid():
    # ESP32 MicroPython commonly starts at year 2000 when the RTC is unset.
    return time.localtime()[0] >= 2024


def sync_time():
    global _synchronized, _last_error
    try:
        import ntptime
    except ImportError:
        _last_error = "ntptime module unavailable"
        print("NTP:", _last_error)
        return False

    ntptime.host = NTP_HOST
    for attempt in range(1, NTP_RETRIES + 1):
        try:
            ntptime.settime()
            _synchronized = is_time_valid()
            _last_error = None
            print("NTP synchronized from", NTP_HOST)
            return _synchronized
        except Exception as exc:
            _last_error = str(exc)
            print("NTP attempt %d/%d failed: %s" % (attempt, NTP_RETRIES, exc))
            if attempt < NTP_RETRIES:
                time.sleep(NTP_RETRY_DELAY_SECONDS)
    return False


def synchronized():
    return _synchronized or is_time_valid()


def last_error():
    return _last_error
