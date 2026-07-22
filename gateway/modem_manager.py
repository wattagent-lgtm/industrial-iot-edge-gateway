"""Supervised A7670 LTE modem service for the classic T-A7670 R2.

This stage activates and monitors the modem's internal PDP context. Cloud sockets
are intentionally left for the next transport layer.
"""

import machine
import time
import uasyncio as asyncio

from config import (MODEM_UART_ID, MODEM_BAUDRATE, MODEM_RX_PIN, MODEM_TX_PIN,
                    MODEM_PWRKEY_PIN, MODEM_RESET_PIN, MODEM_DTR_PIN,
                    MODEM_POWER_ENABLE_PIN, MODEM_APN, MODEM_COMMAND_TIMEOUT_MS,
                    MODEM_STARTUP_TIMEOUT_SECONDS, MODEM_MONITOR_INTERVAL_SECONDS,
                    MODEM_INTERNET_TEST_INTERVAL_SECONDS, MODEM_PING_HOST,
                    MODEM_PING_TIMEOUT_SECONDS)


class ModemManager:
    def __init__(self, logger):
        self.logger = logger
        self.uart = None
        self.running = False
        self.responding = False
        self.sim_status = "UNKNOWN"
        self.operator = "UNKNOWN"
        self.registration = "NOT REGISTERED"
        self.signal_csq = None
        self.signal_dbm = None
        self.data_attached = False
        self.data_active = False
        self.mobile_ip = None
        self.model = "A7670"
        self.last_check = "Never"
        self.last_error = None
        self.reconnect_count = 0
        self.internet_ok = False
        self.ping_latency_ms = None
        self.last_internet_test = "Never"
        self.internet_test_failures = 0
        self.internet_test_running = False
        self._last_test_ticks = None
        self.lock = asyncio.Lock()
        self._last_logged_state = None
        self._pdp_configured = False

    async def start(self):
        self.running = True
        try:
            self._initialize_hardware()
            if not await self._wait_for_modem():
                self.logger.warning("LTE modem did not answer; applying PWRKEY sequence")
                await self._power_key_sequence()
            if not await self._wait_for_modem():
                raise OSError("A7670 did not respond to AT commands")
            self.responding = True
            self.logger.info("LTE modem responding")
            await self._configure_and_check()
        except Exception as exc:
            self._record_error(exc)

        while True:
            await asyncio.sleep(MODEM_MONITOR_INTERVAL_SECONDS)
            try:
                if not self.responding:
                    self.reconnect_count += 1
                    self.responding = await self._wait_for_modem()
                    if self.responding:
                        # The modem may have rebooted and lost its PDP profile.
                        self._pdp_configured = False
                if self.responding:
                    await self._configure_and_check()
                    due = (self._last_test_ticks is None or
                           time.ticks_diff(time.ticks_ms(), self._last_test_ticks) >=
                           MODEM_INTERNET_TEST_INTERVAL_SECONDS * 1000)
                    if self.data_active and due:
                        await self.test_internet()
            except Exception as exc:
                self.responding = False
                self._record_error(exc)

    def _initialize_hardware(self):
        machine.Pin(MODEM_POWER_ENABLE_PIN, machine.Pin.OUT, value=1)
        machine.Pin(MODEM_DTR_PIN, machine.Pin.OUT, value=0)
        machine.Pin(MODEM_RESET_PIN, machine.Pin.OUT, value=0)
        self.pwrkey = machine.Pin(MODEM_PWRKEY_PIN, machine.Pin.OUT, value=0)
        self.uart = machine.UART(MODEM_UART_ID, baudrate=MODEM_BAUDRATE,
                                 tx=MODEM_TX_PIN, rx=MODEM_RX_PIN,
                                 timeout=100, timeout_char=50)
        self._drain_uart()

    async def _power_key_sequence(self):
        self.pwrkey.value(0)
        await asyncio.sleep_ms(100)
        self.pwrkey.value(1)
        await asyncio.sleep_ms(1100)
        self.pwrkey.value(0)
        await asyncio.sleep_ms(3000)

    async def _wait_for_modem(self):
        deadline = time.ticks_add(time.ticks_ms(), MODEM_STARTUP_TIMEOUT_SECONDS * 1000)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            try:
                response = await self.command("AT", 1000)
                if "OK" in response:
                    return True
            except Exception:
                pass
            await asyncio.sleep_ms(500)
        return False

    async def _configure_and_check(self):
        self.responding = True
        identity = await self.command("ATI")
        self.model = self._identity(identity)
        self.sim_status = self._after_colon(await self.command("AT+CPIN?"), "+CPIN:")
        csq = self._after_colon(await self.command("AT+CSQ"), "+CSQ:")
        self._set_signal(csq)
        registration = await self.command("AT+CEREG?")
        self._set_registration(registration)
        self.operator = self._operator(await self.command("AT+COPS?"))

        if self.sim_status == "READY" and self.registration == "REGISTERED":
            # APN configuration is persistent during a modem session. Avoid
            # rewriting it during every health poll.
            if not self._pdp_configured:
                await self.command('AT+CGDCONT=1,"IP","%s"' % MODEM_APN)
                self._pdp_configured = True
            attached = self._after_colon(await self.command("AT+CGATT?"), "+CGATT:")
            self.data_attached = attached == "1"
            if not self.data_attached:
                await self.command("AT+CGATT=1", 10000)
                self.data_attached = True
            self.mobile_ip = self._ip_address(await self.command("AT+CGPADDR=1", allow_error=True))
            activation_ok = False
            if not self.mobile_ip:
                activation = await self.command("AT+CGACT=1,1", 10000,
                                                allow_error=True)
                activation_ok = "ERROR" not in activation
                self.mobile_ip = self._ip_address(
                    await self.command("AT+CGPADDR=1", allow_error=True))
            self.data_active = bool(self.mobile_ip) or activation_ok
        else:
            self.data_attached = False
            self.data_active = False
            self.mobile_ip = None

        self.last_check = self._clock_text()
        self.last_error = None
        # Signal naturally fluctuates and remains available through the status API.
        # Log only operational state transitions to avoid one record per poll.
        state = (self.sim_status, self.registration, self.mobile_ip,
                 self.data_active)
        if state != self._last_logged_state:
            self.logger.info("LTE: SIM=%s NET=%s CSQ=%s IP=%s" % (
                self.sim_status, self.registration, self.signal_csq,
                self.mobile_ip or "None"))
            self._last_logged_state = state

    async def command(self, command, timeout_ms=MODEM_COMMAND_TIMEOUT_MS,
                      allow_error=False):
        async with self.lock:
            return await self._command_unlocked(command, timeout_ms, allow_error)

    async def _command_unlocked(self, command, timeout_ms=MODEM_COMMAND_TIMEOUT_MS,
                                allow_error=False):
        self._drain_uart()
        self.uart.write((command + "\r\n").encode())
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        response = bytearray()
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if self.uart.any():
                chunk = self.uart.read()
                if chunk:
                    response.extend(chunk)
                    text = response.decode("utf-8", "ignore")
                    if "\r\nOK\r\n" in text:
                        return text
                    if "\r\nERROR\r\n" in text or "+CME ERROR:" in text:
                        if allow_error:
                            return text
                        raise OSError(command + " returned ERROR")
            await asyncio.sleep_ms(20)
        raise OSError(command + " timed out")

    async def command_until(self, command, marker, timeout_ms=30000):
        """Run an AT command and retain the UART until its asynchronous result."""
        async with self.lock:
            self._drain_uart()
            self.uart.write((command + "\r\n").encode())
            return await self._read_until(marker, timeout_ms)

    async def prompt_upload(self, command, data, timeout_ms=30000):
        """Send binary-safe data after an AT command's input prompt."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        async with self.lock:
            self._drain_uart()
            self.uart.write((command + "\r\n").encode())
            await self._read_until(">", min(timeout_ms, 10000))
            self.uart.write(data)
            return await self._read_until("\r\nOK\r\n", timeout_ms)

    async def _read_until(self, marker, timeout_ms):
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        response = bytearray()
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if self.uart.any():
                chunk = self.uart.read()
                if chunk:
                    response.extend(chunk)
                    text = response.decode("utf-8", "ignore")
                    if marker in text:
                        return text
                    if "\r\nERROR\r\n" in text or "+CME ERROR:" in text:
                        raise OSError("modem returned ERROR")
            await asyncio.sleep_ms(20)
        raise OSError("modem response timeout waiting for " + marker)

    async def read_mqtt_event(self, timeout_ms=100):
        """Collect one unsolicited A76XX MQTT receive event, if available."""
        async with self.lock:
            deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
            response = bytearray()
            started = False
            while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                if self.uart.any():
                    chunk = self.uart.read()
                    if chunk:
                        response.extend(chunk)
                        text = response.decode("utf-8", "ignore")
                        if "+CMQTTRXSTART:" in text:
                            started = True
                            # Allow the full topic/payload event to arrive.
                            deadline = time.ticks_add(time.ticks_ms(), 3000)
                        if started and "+CMQTTRXEND:" in text:
                            return text
                await asyncio.sleep_ms(10)
            return None

    async def test_internet(self):
        """Ping a public IP through LTE and retain a compact health result."""
        self._last_test_ticks = time.ticks_ms()
        self.last_internet_test = self._clock_text()
        if not self.responding or not self.data_active:
            self.internet_ok = False
            self.ping_latency_ms = None
            self.internet_test_failures += 1
            return self.internet_status()

        command = 'AT+CPING="%s",1,3,32,1000,10000,64' % MODEM_PING_HOST
        response = bytearray()
        try:
            async with self.lock:
                self._drain_uart()
                self.uart.write((command + "\r\n").encode())
                deadline = time.ticks_add(time.ticks_ms(), MODEM_PING_TIMEOUT_SECONDS * 1000)
                while time.ticks_diff(deadline, time.ticks_ms()) > 0:
                    if self.uart.any():
                        chunk = self.uart.read()
                        if chunk:
                            response.extend(chunk)
                            text = response.decode("utf-8", "ignore")
                            if "+CPING: 3," in text or "\r\nERROR\r\n" in text:
                                break
                    await asyncio.sleep_ms(20)
            text = response.decode("utf-8", "ignore")
            latencies = []
            for line in text.replace("\r", "").split("\n"):
                if line.startswith("+CPING: 1,"):
                    fields = line.split(",")
                    if len(fields) > 3:
                        try:
                            latencies.append(int(fields[3]))
                        except ValueError:
                            pass
            self.internet_ok = bool(latencies)
            self.ping_latency_ms = sum(latencies) // len(latencies) if latencies else None
            if self.internet_ok:
                self.logger.info("LTE internet test OK: %d ms" % self.ping_latency_ms)
            else:
                self.internet_test_failures += 1
                self.logger.warning("LTE internet test failed")
        except Exception as exc:
            self.internet_ok = False
            self.ping_latency_ms = None
            self.internet_test_failures += 1
            self.logger.warning("LTE internet test: " + str(exc))
        return self.internet_status()

    def start_internet_test(self):
        """Start one background test without holding an HTTP connection open."""
        if self.internet_test_running:
            return False
        self.internet_test_running = True
        asyncio.create_task(self._internet_test_task())
        return True

    async def _internet_test_task(self):
        try:
            await self.test_internet()
        finally:
            self.internet_test_running = False

    def internet_status(self):
        return {"internet_ok": self.internet_ok, "ping_host": MODEM_PING_HOST,
                "ping_latency_ms": self.ping_latency_ms,
                "last_internet_test": self.last_internet_test,
                "internet_test_failures": self.internet_test_failures,
                "internet_test_running": self.internet_test_running}

    def _drain_uart(self):
        if self.uart:
            while self.uart.any():
                self.uart.read()

    def _record_error(self, exc):
        self.last_error = str(exc)
        self.logger.error("LTE modem: " + self.last_error)

    def _set_signal(self, value):
        try:
            self.signal_csq = int(value.split(",", 1)[0])
            self.signal_dbm = None if self.signal_csq == 99 else 2 * self.signal_csq - 113
        except Exception:
            self.signal_csq = None
            self.signal_dbm = None

    def _set_registration(self, response):
        value = self._after_colon(response, "+CEREG:")
        try:
            fields = value.split(",")
            # Query form is +CEREG: <n>,<stat>[,...]; stat is the second field.
            status = int(fields[1] if len(fields) > 1 else fields[0])
        except Exception:
            status = 0
        self.registration = "REGISTERED" if status in (1, 5) else "NOT REGISTERED"

    @staticmethod
    def _after_colon(response, prefix):
        for line in response.replace("\r", "").split("\n"):
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip()
        return "UNKNOWN"

    @staticmethod
    def _operator(response):
        try:
            return response.split('"', 2)[1]
        except Exception:
            return "UNKNOWN"

    @staticmethod
    def _identity(response):
        ignored = ("ATI", "OK", "")
        for line in response.replace("\r", "").split("\n"):
            if line.strip() not in ignored:
                return line.strip()
        return "A7670"

    @staticmethod
    def _ip_address(response):
        value = ModemManager._after_colon(response, "+CGPADDR:")
        parts = value.replace('"', "").split(",")
        return parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

    @staticmethod
    def _clock_text():
        now = time.localtime()
        return "%04d-%02d-%02d %02d:%02d:%02d UTC" % (
            now[0], now[1], now[2], now[3], now[4], now[5])

    def status(self):
        return {"enabled": True, "responding": self.responding,
                "model": self.model, "sim_status": self.sim_status,
                "operator": self.operator, "registration": self.registration,
                "signal_csq": self.signal_csq, "signal_dbm": self.signal_dbm,
                "data_attached": self.data_attached, "data_active": self.data_active,
                "mobile_ip": self.mobile_ip, "apn": MODEM_APN,
                "last_check": self.last_check, "last_error": self.last_error,
                "reconnect_count": self.reconnect_count,
                "internet_ok": self.internet_ok, "ping_host": MODEM_PING_HOST,
                "ping_latency_ms": self.ping_latency_ms,
                "last_internet_test": self.last_internet_test,
                "internet_test_failures": self.internet_test_failures}
