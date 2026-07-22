"""Small MicroPython-compatible helpers shared by gateway services."""

import time
import uasyncio as asyncio
from config import TIMEZONE_OFFSET_HOURS

try:
    import ujson as json
except ImportError:
    import json


BOOT_TICKS = time.ticks_ms()


def uptime_seconds():
    return time.ticks_diff(time.ticks_ms(), BOOT_TICKS) // 1000


def iso_time():
    """Return a compact configured-local-time timestamp."""
    t = time.localtime(time.time() + TIMEZONE_OFFSET_HOURS * 3600)
    return "%04d-%02d-%02d %02d:%02d:%02d" % (
        t[0], t[1], t[2], t[3], t[4], t[5]
    )


def json_dumps(value):
    return json.dumps(value)


def parse_json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def peer_ip(writer):
    try:
        peer = writer.get_extra_info("peername")
        return peer[0] if peer else "unknown"
    except Exception:
        return "unknown"


async def close_writer(writer):
    """Close a stream without allowing wait_closed() to leak a task forever."""
    try:
        writer.close()
    except Exception:
        return
    try:
        wait_closed = getattr(writer, "wait_closed", None)
        if wait_closed:
            await asyncio.wait_for_ms(wait_closed(), 250)
        else:
            await asyncio.sleep_ms(0)
    except Exception:
        pass
