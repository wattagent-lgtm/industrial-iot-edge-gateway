"""Bounded AWS IoT MQTT/TLS publisher using the A7670 AT command stack."""

import gc
import uasyncio as asyncio

from config import (MQTT_BROKER, MQTT_PORT, MQTT_CLIENT_ID,
                    MQTT_KEEPALIVE_SECONDS, MQTT_QUEUE_CAPACITY,
                    MQTT_RECONNECT_MAX_SECONDS, MQTT_TOPIC_PREFIX,
                    MQTT_COMMAND_TOPIC, MQTT_RESPONSE_TOPIC,
                    MQTT_CA_FILE, MQTT_CERT_FILE, MQTT_KEY_FILE)
from utils import json_dumps, parse_json, iso_time, uptime_seconds


class MQTTManager:
    def __init__(self, modem, logger):
        self.modem = modem
        self.logger = logger
        self.queue = []
        self.connected = False
        self.state = "STARTING"
        self.published = 0
        self.failed = 0
        self.dropped = 0
        self.coalesced = 0
        self.priority_evictions = 0
        self.last_error = None
        self.last_topic = None
        self.commands_received = 0
        self.commands_rejected = 0

    def enqueue(self, payload, parsed):
        topic = self._topic(parsed)
        kind = self._message_kind(parsed)

        # Latest-value coalescing prevents periodic telemetry for the same UNS
        # topic from consuming every queue slot while the cellular modem is
        # slower than the edge sampling rate. Events are never coalesced.
        if kind != "event":
            for index in range(len(self.queue) - 1, -1, -1):
                entry = self.queue[index]
                if entry[0] == topic and entry[2] != "event":
                    self.queue[index] = (topic, payload, kind)
                    self.coalesced += 1
                    return True

        if kind == "event":
            return self._enqueue_important(topic, payload, kind)

        if len(self.queue) >= MQTT_QUEUE_CAPACITY:
            # Preserve queued events and command responses. The latest value
            # for this topic will be accepted on a later client update.
            self.dropped += 1
            return False
        self.queue.append((topic, payload, kind))
        return True

    async def start(self):
        delay = 5
        while True:
            try:
                if not self.modem.responding or not self.modem.data_active:
                    self.state = "WAITING FOR LTE"
                    await asyncio.sleep(5)
                    continue
                if not self.connected:
                    await self._connect()
                    delay = 5
                if self.queue:
                    topic, payload, kind = self.queue[0]
                    await self._publish(topic, payload)
                    self.queue.pop(0)
                    self.published += 1
                    self.last_topic = topic
                else:
                    event = await self.modem.read_mqtt_event(200)
                    if event:
                        await self._handle_event(event)
                    else:
                        await asyncio.sleep_ms(50)
            except Exception as exc:
                self.connected = False
                self.state = "RECONNECTING"
                self.failed += 1
                self.last_error = str(exc)
                self.logger.warning("MQTT: %s" % self.last_error)
                await self._cleanup()
                gc.collect()
                await asyncio.sleep(delay)
                delay = min(delay * 2, MQTT_RECONNECT_MAX_SECONDS)

    async def _connect(self):
        self.state = "PROVISIONING"
        await self._provision_certificates()
        await self._cleanup()

        # Configure mutual TLS before starting the MQTT service, matching the
        # SIMCom A76XX MQTT(S) sequence.
        await self.modem.command('AT+CSSLCFG="sslversion",0,3')
        await self.modem.command('AT+CSSLCFG="authmode",0,2')
        await self.modem.command('AT+CSSLCFG="cacert",0,"aws-root.pem"')
        await self.modem.command('AT+CSSLCFG="clientcert",0,"aws-device.pem"')
        await self.modem.command('AT+CSSLCFG="clientkey",0,"aws-key.pem"')
        await self.modem.command('AT+CSSLCFG="enableSNI",0,1')

        response = await self.modem.command_until(
            "AT+CMQTTSTART", "+CMQTTSTART:", 30000)
        self._require_result(response, "+CMQTTSTART:")
        await self.modem.command('AT+CMQTTACCQ=0,"%s",1' % MQTT_CLIENT_ID)
        await self.modem.command("AT+CMQTTSSLCFG=0,0")

        self.state = "CONNECTING"
        command = 'AT+CMQTTCONNECT=0,"tcp://%s:%d",%d,1' % (
            MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE_SECONDS)
        response = await self.modem.command_until(command, "+CMQTTCONNECT:", 90000)
        self._require_result(response, "+CMQTTCONNECT:")
        await self.modem.prompt_upload(
            "AT+CMQTTSUBTOPIC=0,%d,1" % len(MQTT_COMMAND_TOPIC.encode("utf-8")),
            MQTT_COMMAND_TOPIC, 10000)
        response = await self.modem.command_until(
            "AT+CMQTTSUB=0", "+CMQTTSUB:", 30000)
        self._require_result(response, "+CMQTTSUB:")
        self.connected = True
        self.state = "CONNECTED"
        self.last_error = None
        self.logger.info("MQTT connected to AWS IoT Core")
        self.logger.info("MQTT subscribed: " + MQTT_COMMAND_TOPIC)

    async def _handle_event(self, event):
        topic, payload = self._parse_event(event)
        if topic != MQTT_COMMAND_TOPIC or payload is None:
            return
        self.commands_received += 1
        request_id = None
        try:
            request = parse_json(payload)
            if not isinstance(request, dict):
                raise ValueError("command must be an object")
            request_id = request.get("request_id")
            if request.get("command") != "get_status":
                self.commands_rejected += 1
                response = {"status": "REJECTED", "request_id": request_id,
                            "error": "command not allowed",
                            "timestamp": iso_time()}
            else:
                response = {"status": "OK", "command": "get_status",
                            "request_id": request_id, "gateway_id": MQTT_CLIENT_ID,
                            "timestamp": iso_time(),
                            "uptime_seconds": uptime_seconds(),
                            "free_memory_bytes": gc.mem_free(),
                            "lte_registration": self.modem.registration,
                            "lte_signal_dbm": self.modem.signal_dbm,
                            "lte_mobile_ip": self.modem.mobile_ip,
                            "mqtt_published": self.published,
                            "mqtt_queue_depth": len(self.queue)}
        except Exception as exc:
            self.commands_rejected += 1
            response = {"status": "REJECTED", "request_id": request_id,
                        "error": str(exc), "timestamp": iso_time()}
        self._enqueue_priority(MQTT_RESPONSE_TOPIC, json_dumps(response))

    def _enqueue_priority(self, topic, payload):
        return self._enqueue_important(topic, payload, "response")

    def _enqueue_important(self, topic, payload, kind):
        """Insert an event/response without allowing telemetry to evict it."""
        if len(self.queue) >= MQTT_QUEUE_CAPACITY:
            remove_at = self._lowest_priority_index()
            if remove_at < 0:
                # The queue contains only events/responses. Dropping the
                # incoming item is safer than silently losing an older event.
                self.dropped += 1
                return False
            self.queue.pop(remove_at)
            self.dropped += 1
            self.priority_evictions += 1
        # Keep important messages ahead of telemetry while preserving FIFO
        # order among events/responses.
        insert_at = 0
        while (insert_at < len(self.queue) and
               self.queue[insert_at][2] in ("event", "response")):
            insert_at += 1
        self.queue.insert(insert_at, (topic, payload, kind))
        return True

    def _lowest_priority_index(self):
        # Diagnostic waveforms are cheapest to discard, followed by periodic
        # telemetry. Search from the tail to evict an older low-priority item.
        for wanted in ("diagnostic", "fast", "slow", "telemetry"):
            for index in range(len(self.queue) - 1, -1, -1):
                if self.queue[index][2] == wanted:
                    return index
        return -1

    @staticmethod
    def _message_kind(parsed):
        message_type = str(parsed.get("message_type", "telemetry")).lower()
        data_class = str(parsed.get("data_class", "")).lower()
        if message_type == "event" or data_class == "event":
            return "event"
        if message_type == "diagnostic" or data_class == "diagnostic":
            return "diagnostic"
        if data_class == "fast":
            return "fast"
        if data_class == "slow":
            return "slow"
        return "telemetry"

    @staticmethod
    def _parse_event(event):
        """Extract topic and payload from a +CMQTTRXSTART...RXEND block."""
        text = event.replace("\r", "")
        return (MQTTManager._event_value(text, "+CMQTTRXTOPIC:"),
                MQTTManager._event_value(text, "+CMQTTRXPAYLOAD:"))

    @staticmethod
    def _event_value(text, marker):
        position = text.find(marker)
        if position < 0:
            return None
        line_end = text.find("\n", position)
        if line_end < 0:
            return None
        try:
            length = int(text[position:line_end].rsplit(",", 1)[1])
        except Exception:
            return None
        # Slice by the length reported by the modem so formatted, multi-line
        # JSON payloads from the AWS console remain intact.
        return text[line_end + 1:line_end + 1 + length]

    async def _provision_certificates(self):
        listed = await self.modem.command("AT+CCERTLIST", 10000,
                                          allow_error=True)
        files = (("aws-root.pem", MQTT_CA_FILE),
                 ("aws-device.pem", MQTT_CERT_FILE),
                 ("aws-key.pem", MQTT_KEY_FILE))
        for remote_name, local_path in files:
            if remote_name in listed:
                continue
            with open(local_path, "rb") as source:
                data = source.read()
            if not data or len(data) > 10240:
                raise OSError("invalid certificate file " + local_path)
            command = 'AT+CCERTDOWN="%s",%d' % (remote_name, len(data))
            await self.modem.prompt_upload(command, data, 120000)
            data = None
            gc.collect()
            self.logger.info("MQTT certificate installed: " + remote_name)

    async def _publish(self, topic, payload):
        await self.modem.prompt_upload(
            "AT+CMQTTTOPIC=0,%d" % len(topic.encode("utf-8")), topic, 10000)
        await self.modem.prompt_upload(
            "AT+CMQTTPAYLOAD=0,%d" % len(payload.encode("utf-8")), payload, 30000)
        response = await self.modem.command_until(
            "AT+CMQTTPUB=0,1,60", "+CMQTTPUB:", 70000)
        self._require_result(response, "+CMQTTPUB:")

    async def _cleanup(self):
        for command in ("AT+CMQTTDISC=0,30", "AT+CMQTTREL=0", "AT+CMQTTSTOP"):
            try:
                await self.modem.command(command, 5000, allow_error=True)
            except Exception:
                pass

    @staticmethod
    def _require_result(response, prefix):
        for line in response.replace("\r", "").split("\n"):
            if line.startswith(prefix):
                fields = line.split(":", 1)[1].split(",")
                try:
                    if int(fields[-1].strip()) == 0:
                        return
                except Exception:
                    pass
        raise OSError(prefix + " operation failed")

    def _topic(self, parsed):
        area = self._safe(parsed.get("area", parsed.get("site", "process")))
        device_type = self._safe(parsed.get("device_type", "device"))
        device_id = self._safe(parsed.get("device_id",
                                          parsed.get("node_id", "unknown")))
        message_type = str(parsed.get("message_type", "telemetry")).lower()
        data_class = str(parsed.get("data_class", "")).lower()
        if message_type == "event" or data_class == "event":
            suffix = "event"
        elif message_type == "diagnostic" or data_class == "diagnostic":
            suffix = "diagnostic"
        elif data_class == "fast":
            suffix = "telemetry/fast"
        elif data_class == "slow":
            suffix = "telemetry/slow"
        else:
            # Preserve the original topic for existing clients.
            suffix = "telemetry"
        return "%s/%s/%s/%s/%s" % (
            MQTT_TOPIC_PREFIX, area, device_type, device_id, suffix)

    @staticmethod
    def _safe(value):
        value = str(value).strip().lower()
        result = []
        for char in value:
            # Some MicroPython str implementations do not expose isalnum().
            code = ord(char)
            valid = ((48 <= code <= 57) or (97 <= code <= 122) or char == "-")
            result.append(char if valid else "-")
        return "".join(result)[:40] or "unknown"

    def status(self):
        return {"enabled": True, "state": self.state,
                "connected": self.connected, "broker": MQTT_BROKER,
                "queued": len(self.queue), "published": self.published,
                "failed": self.failed, "dropped": self.dropped,
                "coalesced": self.coalesced,
                "priority_evictions": self.priority_evictions,
                "last_error": self.last_error, "last_topic": self.last_topic,
                "commands_received": self.commands_received,
                "commands_rejected": self.commands_rejected}
