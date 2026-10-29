"""Offline simulated device memory uploaded through the existing JSONL receiver."""

from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from doctorcar.core.models import Event, Sample
from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.monitoring.event_detector import EventDetector
from doctorcar.monitoring.event_recorder import EventRecorder
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.messages import envelope
from doctorcar.protocol.receiver import ProtocolReceiver
from doctorcar.protocol.simulator import device_messages, event_messages
from doctorcar.sources.faults import FaultInstance
from doctorcar.sources.serial_device import ProtocolSource
from doctorcar.sources.simulation import SimulationSource

HISTORY_PROVENANCE = "SIMULATED DEVICE HISTORY"


class _Memory:
    """A sink for the existing recorder, not a second recording implementation."""

    def __init__(self) -> None:
        self.events: dict[str, Event] = {}

    def save_event(self, event: Event) -> None:
        self.events[event.event_id] = Event.from_dict(event.to_dict())


def historical_events(seed: int = 42, count: int = 2) -> tuple[Event, ...]:
    if not 1 <= count <= 2:
        raise ValueError("History count must be 1 or 2")
    result: list[Event] = []
    for index in range(count):
        source = SimulationSource(
            seed=seed + index,
            step_ms=1000,
            duration_ms=110_000,
            mode="FAULT_INJECTION",
            faults=(FaultInstance("thermal_sudden" if index == 0 else "sensor_dropout"),),
        )
        source.connect()
        source.session_id = str(uuid5(NAMESPACE_URL, f"doctorcar:history-v1:{seed}:{index}"))
        source.start()
        memory, validator, detector = _Memory(), DataQualityValidator(), EventDetector()
        recorder = EventRecorder(memory)
        try:
            while (sample := source.read_measurements()) is not None:
                validated = validator.validate_measurement(
                    replace(sample, provenance=HISTORY_PROVENANCE, received_at_ms=None)
                )
                recorder.append_measurement(
                    validated.sample, detector.evaluate_trigger(validated.sample, validated.issues)
                )
            recorder.stop()
        finally:
            source.stop()
            source.disconnect()
        result.extend(memory.events.values())
    return tuple(result)


def historical_device_messages(seed: int = 42, count: int = 2) -> Iterator[dict[str, Any]]:
    device = "doctorcar-software-simulator"
    for event in historical_events(seed, count):
        yield envelope(
            "HELLO",
            device,
            event.session_id,
            0,
            0,
            "SIMULATION",
            {"firmware_version": "software-history-1", "test_mode": True},
        )
        yield envelope(
            "CAPABILITIES",
            device,
            event.session_id,
            1,
            0,
            "SIMULATION",
            {
                "sensors": list(event.samples[0].readings) + ["DTC"],
                "can": False,
                "microsd": False,
                "event_upload": True,
            },
        )
        yield from event_messages(event)
    yield from device_messages("normal", seed, step_ms=1000)


class SimulatedDeviceSource(ProtocolSource):
    def __init__(self, seed: int = 42, history_count: int = 2) -> None:
        super().__init__()
        if not 1 <= history_count <= 2:
            raise ValueError("History count must be 1 or 2")
        self.seed, self.history_count = seed, history_count
        self.messages: Iterator[dict[str, Any]] = iter(())

    def connect(self) -> None:
        if self.state != "DISCONNECTED":
            raise RuntimeError("Simulated device already open")
        self.receiver = ProtocolReceiver()
        self.messages = historical_device_messages(self.seed, self.history_count)
        self.state, self.exhausted = "CONNECTED", False

    def read_measurements(self) -> Sample | None:
        if self.state != "RUNNING":
            return None
        message = next(self.messages, None)
        if message is None:
            self.exhausted = True
            return None
        self._feed(encode_message(message))
        return self.receiver.samples.popleft() if self.receiver.samples else None

    def disconnect(self) -> None:
        close = getattr(self.messages, "close", None)
        if close:
            close()
        super().disconnect()
