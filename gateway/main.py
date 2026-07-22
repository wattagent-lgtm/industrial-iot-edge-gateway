"""Application entry point with fail-safe recovery.

An unhandled task exception must not leave the ESP32 responding to ICMP while
TCP and HTTP are permanently offline. The most recent exception is persisted
for diagnosis and a hardware reset clears any stale lwIP/UART state.
"""

import gc
import sys
import time
import machine
import network
import uasyncio as asyncio

from config import CRASH_LOG_FILE, CRASH_RESTART_DELAY_SECONDS
from gateway import start_gateway


def _save_crash(exc):
    """Persist only the latest crash to bound flash usage."""
    try:
        with open(CRASH_LOG_FILE, "w") as crash_file:
            crash_file.write("reset_cause=%s free_memory=%s\n" %
                             (machine.reset_cause(), gc.mem_free()))
            sys.print_exception(exc, crash_file)
    except Exception as log_error:
        print("Unable to save crash log:", log_error)


wlan = network.WLAN(network.STA_IF)
print("Gateway IP:", wlan.ifconfig()[0])

try:
    asyncio.run(start_gateway())
except Exception as exc:
    # KeyboardInterrupt is intentionally not caught, so a developer can still
    # stop the application and reach the REPL with Ctrl+C.
    print("FATAL gateway exception:")
    sys.print_exception(exc)
    _save_crash(exc)
    gc.collect()
    print("Restarting gateway in %s seconds" % CRASH_RESTART_DELAY_SECONDS)
    time.sleep(CRASH_RESTART_DELAY_SECONDS)
    machine.reset()
finally:
    # Helps cleanly return to the REPL when the application is interrupted.
    try:
        asyncio.new_event_loop()
    except AttributeError:
        pass
