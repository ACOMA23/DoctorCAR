"""Bounded framing, handshake, replay protection and atomic event assembly."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

from doctorcar.core.models import Event, Quality, Reading, Sample
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY
from doctorcar.protocol.codec import MAX_LINE_BYTES, decode_message


@dataclass
class Assembly:
    chunks: int
    size: int
    digest: str
    created: float = field(default_factory=time.monotonic)
    parts: dict[int, bytes] = field(default_factory=dict)


class ProtocolReceiver:
    def __init__(self) -> None:
        self.pending = bytearray()
        self.discarding = False
        self.samples: deque[Sample] = deque(maxlen=512)
        self.events: deque[Event] = deque(maxlen=8)
        self.errors: deque[str] = deque(maxlen=100)
        self.last: dict[tuple[str, str], int] = {}
        self.identity: tuple[str, str, str] | None = None
        self.sensors: frozenset[str] | None = None
        self.assemblies: dict[str, Assembly] = {}
        self.sequence_gaps = 0
        self.latest_timestamp_ms: int | None = None
        self.firmware_version = ""
        self.features: dict[str, Any] = {}

    def reset_connection(self) -> None:
        self.pending.clear()
        self.samples.clear()
        self.events.clear()
        self.errors.clear()
        self.discarding = False
        self.identity, self.sensors = None, None
        self.firmware_version, self.features = "", {}
        self.latest_timestamp_ms = None
        self.assemblies.clear()  # interrupted uploads must restart from EVENT_START
        # Keep sequence watermarks for the same boot/session across reconnects.

    def feed(self, data: bytes) -> None:
        for part in data.splitlines(keepends=True):
            if self.discarding:
                if part.endswith(b"\n"):
                    self.discarding = False
                continue
            self.pending.extend(part)
            if len(self.pending) > MAX_LINE_BYTES:
                self.errors.append("oversized_line")
                self.discarding = not self.pending.endswith(b"\n")
                self.pending.clear()
                continue
            if not self.pending.endswith(b"\n"):
                continue
            line = bytes(self.pending)
            self.pending.clear()
            try:
                self.handle_message(decode_message(line))
            except (ValueError, KeyError, TypeError) as exc:
                self.errors.append(str(exc)[:256])

    def validate_sequence(self, message: dict[str, Any]) -> bool:
        key = message["device_id"], message["session_id"]
        seq = message["sequence_number"]
        previous = self.last.get(key)
        if previous is not None and seq <= previous:
            return False
        if previous is not None and seq != previous + 1:
            self.sequence_gaps += 1
            logging.getLogger(__name__).warning(
                "Protocol sequence gap: device=%s session=%s previous=%s current=%s",
                key[0],
                key[1],
                previous,
                seq,
            )
        if key not in self.last and len(self.last) >= 32:
            self.last.pop(next(iter(self.last)))
        self.last[key] = seq
        return True

    def handle_message(self, message: dict[str, Any]) -> None:
        kind, payload = message["type"], message["payload"]
        identity = message["device_id"], message["session_id"], message["source"]
        if kind == "HELLO":
            if not self.validate_sequence(message):
                return
            if self.identity != identity:
                self.assemblies.clear()
                self.sensors = None
                self.latest_timestamp_ms = message["timestamp_ms"]
            self.identity = identity
            self.firmware_version = payload["firmware_version"]
            return
        if self.identity != identity:
            raise ValueError("HELLO is required for this device/session/source")
        if kind != "CAPABILITIES" and self.sensors is None:
            raise ValueError("CAPABILITIES required before data")
        if not self.validate_sequence(message):
            return
        self.latest_timestamp_ms = max(self.latest_timestamp_ms or 0, message["timestamp_ms"])
        if kind == "CAPABILITIES":
            self.sensors = frozenset(payload["sensors"])
            self.features = dict(payload)
        elif kind == "SAMPLE":
            sample = Sample.from_dict(payload["sample"])
            if (
                sample.session_id != message["session_id"]
                or sample.source.value != message["source"]
                or sample.timestamp_ms != message["timestamp_ms"]
            ):
                raise ValueError("Sample/envelope identity mismatch")
            if not set(sample.readings).issubset(self.sensors or frozenset()):
                raise ValueError("Unadvertised sensor")
            if len(self.samples) == self.samples.maxlen:
                raise ValueError("Sample queue full; data loss prevented from being silent")
            readings = dict(sample.readings)
            for sensor_id in NUMERIC_IDS:
                if sensor_id not in (self.sensors or frozenset()):
                    readings[sensor_id] = Reading(
                        None, REGISTRY.get(sensor_id).unit, Quality.UNSUPPORTED
                    )
            self.samples.append(
                replace(
                    sample,
                    readings=readings,
                    dtc_quality=(
                        sample.dtc_quality
                        if "DTC" in (self.sensors or frozenset())
                        else Quality.UNSUPPORTED
                    ),
                    device_id=message["device_id"],
                    received_at_ms=time.time_ns() // 1_000_000,
                    raw=message,
                )
            )
        elif kind.startswith("EVENT_"):
            self._event_message(message)
        elif kind == "ERROR":
            self.errors.append(f"device_error:{payload['code']}:{payload['message']}")

    def _event_message(self, message: dict[str, Any]) -> None:
        now = time.monotonic()
        for key in list(self.assemblies):
            if now - self.assemblies[key].created > 60:
                del self.assemblies[key]
                self.errors.append("event_upload_timeout")
        kind, payload, event_id = message["type"], message["payload"], message["event_id"]
        if kind == "EVENT_START":
            if event_id not in self.assemblies and len(self.assemblies) >= 4:
                raise ValueError("Too many event uploads")
            self.assemblies[event_id] = Assembly(
                payload["total_chunks"], payload["total_bytes"], payload["sha256"]
            )
            return
        assembly = self.assemblies.get(event_id)
        if assembly is None:
            raise ValueError("EVENT_START required")
        if kind == "EVENT_CHUNK":
            index = payload["index"]
            part = base64.b64decode(payload["data"], validate=True)
            if index >= assembly.chunks or len(part) > 1024:
                raise ValueError("Invalid event chunk index/size")
            if hashlib.sha256(part).hexdigest() != payload["sha256"]:
                raise ValueError("Chunk integrity failure")
            if index in assembly.parts and assembly.parts[index] != part:
                raise ValueError("Conflicting duplicate chunk")
            if (
                index not in assembly.parts
                and sum(map(len, assembly.parts.values())) + len(part) > assembly.size
            ):
                raise ValueError("Event exceeds declared size")
            assembly.parts[index] = part
        elif kind == "EVENT_END":
            del self.assemblies[event_id]
            if len(assembly.parts) != assembly.chunks:
                raise ValueError("Incomplete event upload")
            data = b"".join(assembly.parts[i] for i in range(assembly.chunks))
            if (
                len(data) != assembly.size
                or hashlib.sha256(data).hexdigest() != assembly.digest
                or payload["sha256"] != assembly.digest
            ):
                raise ValueError("Event integrity failure")
            event = Event.from_dict(json.loads(data))
            if (
                event.event_id != event_id
                or event.session_id != message["session_id"]
                or event.status not in ("COMPLETE", "PARTIAL")
                or not event.samples
                or any(
                    s.session_id != event.session_id or s.source.value != message["source"]
                    for s in event.samples
                )
            ):
                raise ValueError("Invalid event identity/status/provenance")
            if len(self.events) == self.events.maxlen:
                raise ValueError("Event queue full")
            self.events.append(event)
