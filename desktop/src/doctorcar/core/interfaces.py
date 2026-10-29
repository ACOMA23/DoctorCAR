"""One ingestion contract; optional future analysis uses this same stream."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from doctorcar.core.models import Event, Sample, Trigger


@dataclass(frozen=True)
class Capabilities:
    sensors: frozenset[str]
    source: str
    test_mode: bool = True
    can: bool = False
    microsd: bool = False


class DataSource(ABC):
    state: str = "DISCONNECTED"
    exhausted: bool = False

    @abstractmethod
    def connect(self) -> None: ...

    def start(self) -> None:
        if self.state != "CONNECTED":
            raise RuntimeError("Source must be connected before starting")
        self.state = "RUNNING"

    def stop(self) -> None:
        self.state = "CONNECTED"

    def disconnect(self) -> None:
        self.state = "DISCONNECTED"

    @abstractmethod
    def read_measurements(self) -> Sample | None: ...

    @abstractmethod
    def get_capabilities(self) -> Capabilities: ...

    def get_connection_state(self) -> str:
        return self.state

    def drain_events(self) -> tuple[Event, ...]:
        return ()

    def get_current_timestamp_ms(self) -> int | None:
        """Source clock for live-age checks; offline replay has no wall-clock age."""
        return None

    def get_simulation_metadata(self) -> dict[str, Any] | None:
        return None

    def get_device_info(self) -> dict[str, Any]:
        return {"state": self.state, "source": self.get_capabilities().source}

    def verify(self) -> dict[str, Any]:
        """Explicit software-source check; never starts a persistent session."""
        try:
            self.connect()
            self.start()
            sample = self.read_measurements()
            return {
                "ok": True,
                "stages": ["CONFIGURATION_VALID"],
                "sample_received": sample is not None,
                **self.get_device_info(),
            }
        finally:
            self.stop()
            self.disconnect()


class EventSink(Protocol):
    """Recorder persistence boundary, also used by the software device's offline memory."""

    def save_event(self, event: Event) -> None: ...


class WindowAnalyzer(Protocol):
    """M2 integration contract only; no trained AI is present in M1."""

    def evaluate_window(self, samples: tuple[Sample, ...]) -> tuple[Trigger, ...]: ...
