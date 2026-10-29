"""Experimental loopback-only TCP transport, reusing JSONL v1 validation."""

import ipaddress
import socket
import time
from typing import Any

from doctorcar.core.models import Sample
from doctorcar.protocol.receiver import ProtocolReceiver
from doctorcar.sources.serial_device import ProtocolSource


def local_host(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    if not ipaddress.ip_address(host).is_loopback or ":" in host:
        raise ValueError("Experimental TCP supports IPv4 loopback only; LAN is disabled")
    return host


class NetworkDeviceSource(ProtocolSource):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        timeout: float = 5,
        max_reconnects: int = 2,
    ) -> None:
        super().__init__()
        self.host, self.port = local_host(host), port
        if not 1 <= port <= 65535 or not 0.05 <= timeout <= 30 or not 0 <= max_reconnects <= 3:
            raise ValueError("Invalid TCP configuration")
        self.timeout, self.max_reconnects = timeout, max_reconnects
        self.socket: socket.socket | None = None
        self.reconnects = 0
        self.last_data = self.connected_at = self.retry_at = 0.0

    def connect(self) -> None:
        if self.socket is not None:
            raise RuntimeError("TCP already connected")
        self.socket = socket.create_connection((self.host, self.port), timeout=min(self.timeout, 1))
        self.socket.setblocking(False)
        self.receiver = ProtocolReceiver()  # DB validates retransmitted history identities.
        self.last_data = self.connected_at = time.monotonic()
        self.state, self.exhausted = "CONNECTED", False

    def read_measurements(self) -> Sample | None:
        if self.state == "RECONNECTING":
            if time.monotonic() < self.retry_at:
                return None
            try:
                self.connect()
                self.start()
            except OSError:
                self._retry()
            return None
        if self.socket is None or self.state not in (
            "RUNNING",
            "RECEIVING_DATA",
            "HANDSHAKE_PENDING",
        ):
            return None
        if self.receiver.samples:
            return self.receiver.samples.popleft()
        try:
            data = self.socket.recv(4096)
        except BlockingIOError:
            data = None
        except OSError:
            self._retry()
            return None
        if data == b"":
            if self.receiver.pending or self.receiver.assemblies:
                self.state = "INTERRUPTED_UPLOAD"
            self._retry()
            return None
        if data:
            self._feed(data)
            self.last_data = time.monotonic()
        now = time.monotonic()
        if now - self.last_data > self.timeout or (
            self.receiver.sensors is None and now - self.connected_at > self.timeout
        ):
            self._retry()
            return None
        self.state = "RECEIVING_DATA" if self.receiver.sensors is not None else "HANDSHAKE_PENDING"
        return self.receiver.samples.popleft() if self.receiver.samples else None

    def _retry(self) -> None:
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.reconnects >= self.max_reconnects:
            self.state = "CONNECTION_LOST"
            raise ConnectionError("TCP reconnect budget exhausted")
        self.reconnects += 1
        self.state = "RECONNECTING"
        self.retry_at = time.monotonic() + 0.2 * self.reconnects

    def verify(self) -> dict[str, Any]:
        try:
            self.connect()
            self.start()
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                sample = self.read_measurements()
                if sample is not None:
                    return {
                        "ok": True,
                        "stages": ["HELLO", "CAPABILITIES", "RECEIVING_DATA"],
                        **self.get_device_info(),
                    }
                time.sleep(0.002)
            raise TimeoutError("No sample in TCP verification window")
        finally:
            self.disconnect()

    def disconnect(self) -> None:
        if self.socket:
            self.socket.close()
            self.socket = None
        super().disconnect()

    def get_device_info(self) -> dict[str, Any]:
        return {
            **super().get_device_info(),
            "transport": "TCP_LOOPBACK",
            "host": self.host,
            "port": self.port,
            "reconnects": self.reconnects,
            "vehicle_verified": False,
        }
