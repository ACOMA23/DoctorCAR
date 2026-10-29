"""Versioned measurements; timestamps are elapsed milliseconds within one session."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Source(StrEnum):
    SIMULATION = "SIMULATION"
    REPLAY = "REPLAY"
    DEVICE_TEST = "DEVICE_TEST"


class Quality(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"
    STALE = "STALE"


def integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"Invalid {name}")
    return value


@dataclass(frozen=True)
class Reading:
    value: float | None
    unit: str
    quality: Quality = Quality.AVAILABLE

    def __post_init__(self) -> None:
        if not isinstance(self.unit, str):
            raise ValueError("unit must be text")
        if self.value is not None and (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not math.isfinite(self.value)
        ):
            raise ValueError("reading must be a finite number or null")
        if not isinstance(self.quality, Quality):
            raise ValueError("invalid quality")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reading:
        return cls(data["value"], data["unit"], Quality(data.get("quality", "AVAILABLE")))


@dataclass(frozen=True)
class Sample:
    session_id: str
    source: Source
    sequence_number: int
    timestamp_ms: int
    readings: dict[str, Reading]
    dtcs: tuple[str, ...] = ()
    phase: str = ""
    received_at_ms: int | None = None
    device_id: str | None = None
    provenance: str | None = None
    freeze_frame: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
    dtc_quality: Quality = Quality.MISSING

    def __post_init__(self) -> None:
        identifier(self.session_id, "session_id")
        integer(self.sequence_number, "sequence_number")
        integer(self.timestamp_ms, "timestamp_ms")
        if self.received_at_ms is not None:
            integer(self.received_at_ms, "received_at_ms")
        if not isinstance(self.source, Source):
            raise ValueError("invalid source")
        if not isinstance(self.dtc_quality, Quality):
            raise ValueError("invalid DTC quality")
        if self.freeze_frame is not None and not isinstance(self.freeze_frame, dict):
            raise ValueError("freeze_frame must be an object or null")
        if not isinstance(self.readings, dict) or not all(
            isinstance(k, str) and isinstance(v, Reading) for k, v in self.readings.items()
        ):
            raise ValueError("invalid readings")
        if not isinstance(self.phase, str) or not all(isinstance(x, str) for x in self.dtcs):
            raise ValueError("invalid phase/DTC")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sample_version"] = 1
        data["source"] = self.source.value
        data["readings"] = {
            key: {"value": r.value, "unit": r.unit, "quality": r.quality.value}
            for key, r in self.readings.items()
        }
        data["dtcs"] = list(self.dtcs)
        data["dtc_quality"] = self.dtc_quality.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sample:
        if type(data.get("sample_version")) is not int or data["sample_version"] != 1:
            raise ValueError("Unsupported sample version")
        readings = data["readings"]
        if not isinstance(readings, dict):
            raise ValueError("readings must be an object")
        dtcs = data.get("dtcs", [])
        if not isinstance(dtcs, list) or not all(isinstance(x, str) for x in dtcs):
            raise ValueError("dtcs must be an array of strings")
        return cls(
            session_id=data["session_id"],
            source=Source(data["source"]),
            sequence_number=data["sequence_number"],
            timestamp_ms=data["timestamp_ms"],
            readings={k: Reading.from_dict(v) for k, v in readings.items()},
            dtcs=tuple(dtcs),
            phase=data.get("phase", ""),
            received_at_ms=data.get("received_at_ms"),
            device_id=data.get("device_id"),
            provenance=data.get("provenance"),
            freeze_frame=data.get("freeze_frame"),
            raw=data.get("raw"),
            dtc_quality=Quality(
                data.get("dtc_quality", "AVAILABLE" if "dtcs" in data else "MISSING")
            ),
        )


@dataclass(frozen=True)
class Trigger:
    kind: str
    observation: str
    reason: str
    rule_version: str
    timestamp_ms: int
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.kind, "trigger kind")
        identifier(self.rule_version, "rule version")
        integer(self.timestamp_ms, "trigger timestamp")
        if (
            not isinstance(self.observation, str)
            or not isinstance(self.reason, str)
            or not all(isinstance(x, str) for x in self.evidence)
        ):
            raise ValueError("Invalid trigger text/evidence")


@dataclass
class Event:
    event_id: str
    session_id: str
    trigger: Trigger
    samples: list[Sample] = field(default_factory=list)
    status: str = "RECORDING"
    end_ms: int | None = None
    limitations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        identifier(self.event_id, "event_id")
        identifier(self.session_id, "session_id")
        if self.status not in ("RECORDING", "COMPLETE", "PARTIAL"):
            raise ValueError("Invalid event status")
        if self.end_ms is not None:
            integer(self.end_ms, "event end")
        elif self.status != "RECORDING":
            raise ValueError("Finalized events require an end timestamp")
        if any(s.session_id != self.session_id for s in self.samples):
            raise ValueError("Event session mismatch")
        if any(
            b.timestamp_ms <= a.timestamp_ms or b.sequence_number <= a.sequence_number
            for a, b in zip(self.samples, self.samples[1:], strict=False)
        ):
            raise ValueError("Event samples must have increasing times and sequences")
        if self.status != "RECORDING" and self.samples:
            if (
                self.end_ms != self.samples[-1].timestamp_ms
                or self.end_ms < self.trigger.timestamp_ms
            ):
                raise ValueError("Final event end must match the last sample and follow detection")

    @property
    def origin(self) -> str:
        if self.samples and self.samples[0].source == Source.REPLAY:
            return "REPLAY"
        if self.samples and self.samples[0].provenance == "SIMULATED DEVICE HISTORY":
            return "HISTORICAL"
        return "LIVE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_version": 1,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "trigger": asdict(self.trigger),
            "samples": [s.to_dict() for s in self.samples],
            "status": self.status,
            "end_ms": self.end_ms,
            "limitations": self.limitations,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        if type(data.get("event_version")) is not int or data["event_version"] != 1:
            raise ValueError("Unsupported event version")
        trigger = dict(data["trigger"])
        trigger["evidence"] = tuple(trigger.get("evidence", []))
        return cls(
            identifier(data["event_id"], "event_id"),
            identifier(data["session_id"], "session_id"),
            Trigger(**trigger),
            [Sample.from_dict(s) for s in data["samples"]],
            data["status"],
            data.get("end_ms"),
            list(data.get("limitations", [])),
        )
