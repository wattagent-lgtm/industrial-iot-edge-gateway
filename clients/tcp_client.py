"""One-message-per-connection JSON transport for the gateway."""

import socket
import time
import ujson

import logger
from config import (GATEWAY_IP, GATEWAY_PORT, SOCKET_TIMEOUT_SECONDS,
                    RETRY_DELAY_SECONDS)


class TCPClient:
    def __init__(self, wifi):
        self.wifi = wifi

    def send_with_retry(self, message):
        """Try the exact same message at most twice."""
        for attempt in range(2):
            if not self.wifi.ensure_connected():
                logger.warning("Cannot send while Wi-Fi is unavailable")
            else:
                try:
                    acknowledgement = self._send_once(message)
                    if acknowledgement.get("status") == "OK":
                        self._print_acknowledgement(acknowledgement)
                        return True
                    logger.warning("Gateway acknowledgement did not contain status OK")
                except Exception as exc:
                    logger.warning("TCP attempt %d failed: %s" % (attempt + 1, exc))

            if attempt == 0:
                self.wifi.ensure_connected()
                time.sleep(RETRY_DELAY_SECONDS)
        return False

    def _send_once(self, message):
        connection = None
        try:
            address = socket.getaddrinfo(GATEWAY_IP, GATEWAY_PORT, 0, socket.SOCK_STREAM)[0][-1]
            connection = socket.socket()
            connection.settimeout(SOCKET_TIMEOUT_SECONDS)
            connection.connect(address)

            encoded = (ujson.dumps(message) + "\n").encode("utf-8")
            self._send_all(connection, encoded)

            response = connection.recv(512)
            if not response:
                raise OSError("gateway closed without acknowledgement")
            return ujson.loads(response.decode("utf-8").strip())
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError as exc:
                    logger.warning("Socket close failed: " + str(exc))

    @staticmethod
    def _send_all(connection, data):
        sent = 0
        while sent < len(data):
            count = connection.send(data[sent:])
            if count is None or count <= 0:
                raise OSError("socket send failed")
            sent += count

    @staticmethod
    def _print_acknowledgement(acknowledgement):
        logger.info("Gateway ACK: OK")
        if "gateway_name" in acknowledgement:
            logger.info("Gateway name: " + str(acknowledgement["gateway_name"]))
        if "packet_count" in acknowledgement:
            logger.info("Gateway packet count: " + str(acknowledgement["packet_count"]))

