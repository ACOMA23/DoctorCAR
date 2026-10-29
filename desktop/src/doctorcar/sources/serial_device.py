"""Read-only test-device transport. No vehicle protocol or serial write method."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

import serial
from serial.tools import list_ports

from doctorcar.core.interfaces import Capabilities, DataSource
from doctorcar.core.models import Event, Sample
from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.protocol.codec import MAX_LINE_BYTES, decode_message
from doctorcar.protocol.receiver import ProtocolReceiver


class ProtocolSource(DataSource):
    def __init__(self) -> None:
        self.receiver = ProtocolReceiver()

    def get_capabilities(self) -> Capabilities:
        source = self.receiver.identity[2] if self.receiver.identity else "DEVICE_TEST"
        return Capabilities(self.receiver.sensors or frozenset(), source)

    def drain_events(self) -> tuple[Event, ...]:
        events = tuple(self.receiver.events)
        self.receiver.events.clear()
        return events

    def get_device_info(self) -> dict[str, Any]:
        identity = self.receiver.identity
        return {
            "state": self.state,
            "device_id": identity[0] if identity else None,
            "session_id": identity[1] if identity else None,
            "source": identity[2] if identity else None,
            "firmware_version": self.receiver.firmware_version,
            "protocol_version": 1 if identity else None,
            "capabilities": self.receiver.features,
            "last_timestamp_ms": self.receiver.latest_timestamp_ms,
        }

    def _feed(self, data: bytes) -> None:
        self.receiver.feed(data)
        if self.receiver.errors:
            errors = "; ".join(self.receiver.errors)
            self.receiver.errors.clear()
            raise ValueError(f"خطأ بروتوكول الجهاز: {errors}")


class ProtocolFileSource(ProtocolSource):
    """Software-device/captured protocol file; parsed by the same serial receiver."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.stream: BinaryIO | None = None

    def verify(self) -> dict[str, Any]:
        # Framing/schema and a usable handshake are deliberately separate checks.
        count = 0
        with self.path.open("rb") as stream:
            for line in iter(lambda: stream.readline(MAX_LINE_BYTES + 1), b""):
                decode_message(line)
                count += 1
        receiver = ProtocolReceiver()
        validator = DataQualityValidator()
        samples = events = 0
        with self.path.open("rb") as stream:
            for line in iter(lambda: stream.readline(MAX_LINE_BYTES + 1), b""):
                receiver.feed(line)
                if receiver.errors:
                    return {
                        "ok": False,
                        "file_valid": True,
                        "handshake_valid": False,
                        "stages": ["FILE_VALID", "PROTOCOL_ERROR"],
                        "errors": list(receiver.errors),
                    }
                while receiver.samples:
                    result = validator.validate_measurement(receiver.samples.popleft())
                    if not result.accepted or any(x.startswith("unit:") for x in result.issues):
                        raise ValueError("Invalid protocol sample ordering/units")
                    samples += 1
                for event in receiver.events:
                    event_validator = DataQualityValidator()
                    if any(
                        not event_validator.validate_measurement(s).accepted for s in event.samples
                    ):
                        raise ValueError("Invalid event samples")
                    events += 1
                receiver.events.clear()
        complete = bool(
            receiver.identity
            and receiver.sensors is not None
            and (samples or events)
            and not receiver.assemblies
            and not receiver.pending
        )
        return {
            "ok": complete,
            "file_valid": bool(count),
            "handshake_valid": complete,
            "samples": samples,
            "events": events,
            "stages": ["FILE_VALID", "HANDSHAKE_VALID" if complete else "HANDSHAKE_PENDING"],
        }

    def connect(self) -> None:
        if self.stream is not None:
            raise RuntimeError("Protocol file already open")
        self.stream = self.path.open("rb")
        self.receiver.reset_connection()
        self.exhausted = False
        self.state = "CONNECTED"

    def read_measurements(self) -> Sample | None:
        if self.state != "RUNNING" or self.stream is None:
            return None
        if not self.receiver.samples:
            data = self.stream.read(4096)
            if data:
                self._feed(data)
            else:
                if self.receiver.pending or self.receiver.assemblies:
                    raise ValueError("Truncated protocol stream/event")
                self.exhausted = True
        return self.receiver.samples.popleft() if self.receiver.samples else None

    def disconnect(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        super().disconnect()


class SerialDeviceSource(ProtocolSource):
    def __init__(self, port: str, port_factory: Callable[..., Any] = serial.Serial) -> None:
        super().__init__()
        if not port.strip() or "://" in port:
            raise ValueError("An explicit local serial port is required")
        self.port_name = port
        self.port_factory = port_factory
        self.port: Any = None
        self.last_data = 0.0
        self.connected_at = 0.0
        self.started = False
        self.sample_session: str | None = None
        self.verification_progress: Callable[[str], None] | None = None

    @staticmethod
    def available_ports() -> list[str]:
        return sorted(p.device for p in list_ports.comports())

    def start(self) -> None:
        if self.port is None:
            raise RuntimeError("Port must be opened first")
        self.started = True
        self.state = "HANDSHAKE_PENDING"

    def verify(self) -> dict[str, Any]:
        stages = ["PORT_AVAILABLE" if self.port_name in self.available_ports() else "PORT_UNLISTED"]

        def stage(state: str) -> None:
            stages.append(state)
            if self.verification_progress:
                self.verification_progress(state)

        try:
            stage("CONNECTING")
            self.connect()
            stage("HANDSHAKE_PENDING")
            self.start()
            validator = DataQualityValidator()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                sample = self.read_measurements()
                if self.receiver.sensors is not None and "CONNECTED" not in stages:
                    for state in ("HELLO", "CAPABILITIES", "PROTOCOL_COMPATIBLE", "CONNECTED"):
                        stage(state)
                if sample is not None:
                    result = validator.validate_measurement(sample)
                    if not result.accepted or any(x.startswith("unit:") for x in result.issues):
                        raise ValueError("Invalid serial sample")
                    stage("RECEIVING_DATA")
                    return {"ok": True, "stages": stages, **self.get_device_info()}
                time.sleep(0.005)
            raise TimeoutError("No valid sample within 10 seconds")
        except Exception as exc:
            state = (
                "TIMEOUT"
                if isinstance(exc, TimeoutError)
                else "PROTOCOL_ERROR"
                if isinstance(exc, ValueError)
                else "CONNECTION_LOST"
            )
            stages.append(state)
            return {"ok": False, "stages": stages, "state": state, "error": str(exc)}
        finally:
            self.disconnect()

    def connect(self) -> None:
        if self.port is not None:
            raise RuntimeError("Serial device is already open")
        self.receiver.reset_connection()
        port = self.port_factory(port=None, baudrate=115200, timeout=0, write_timeout=0.2)
        try:
            port.dtr = False
            port.rts = False
            port.port = self.port_name
            port.open()
            self.port = port
            self.last_data = time.monotonic()
            self.connected_at = self.last_data
            self.exhausted = False
            self.state = "PORT_OPEN"
        except Exception:
            port.close()
            raise

    def read_measurements(self) -> Sample | None:
        if not self.started or self.port is None:
            return None
        if (
            self.receiver.identity is None or self.receiver.sensors is None
        ) and time.monotonic() - self.connected_at > 10:
            self.state = "TIMEOUT"
            raise TimeoutError("لم تكتمل مصافحة الجهاز خلال 10 ثوانٍ")
        if not self.receiver.samples:
            try:
                data = self.port.read(4096)
            except (serial.SerialException, OSError) as exc:
                self.state = "CONNECTION_LOST"
                raise ConnectionError("USB serial connection lost") from exc
            if data:
                self.receiver.feed(data)
                # Opening mid-stream is expected: wait for the next periodic HELLO.
                errors = [
                    error
                    for error in self.receiver.errors
                    if not error.startswith("HELLO is required")
                ]
                self.receiver.errors.clear()
                if errors:
                    self.state = "PROTOCOL_ERROR"
                    raise ValueError("خطأ بروتوكول الجهاز: " + "; ".join(errors))
                self.last_data = time.monotonic()
            elif time.monotonic() - self.last_data > 10:
                self.state = "TIMEOUT"
                raise TimeoutError("لم تصل رسائل الجهاز خلال 10 ثوانٍ؛ تحقق من USB والمنفذ")
        sample = self.receiver.samples.popleft() if self.receiver.samples else None
        if sample:
            self.sample_session = sample.session_id
        self.state = (
            "RECEIVING_DATA"
            if sample
            else "CONNECTED"
            if self.receiver.sensors is not None
            else "HANDSHAKE_PENDING"
        )
        return sample

    def disconnect(self) -> None:
        self.started = False
        if self.port is not None:
            self.port.close()
            self.port = None
        super().disconnect()

    def get_current_timestamp_ms(self) -> int | None:
        if self.receiver.identity and self.sample_session != self.receiver.identity[1]:
            return None  # queued prior-session samples have their own clock
        timestamp = self.receiver.latest_timestamp_ms
        return (
            timestamp + int((time.monotonic() - self.last_data) * 1000)
            if timestamp is not None
            else None
        )
