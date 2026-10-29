"""Shared fixtures for DC-CR-005 tests. Streams are the real simulator, never mocked samples."""

from types import SimpleNamespace
from typing import Any

from doctorcar.analysis.explanation import explain
from doctorcar.analysis.model import AnomalyModel
from doctorcar.analysis.windows import WindowBuilder
from doctorcar.core.models import Event, Reading, Sample, Source, Trigger
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource


def make_source(scenarios: tuple[ScenarioInstance, ...] = (), seed: int = 4100, **kwargs: Any):
    return SimulationSource(
        seed=seed,
        scenario_family="multisensor",
        mode="FAULT_INJECTION" if scenarios else "NORMAL",
        scenarios=scenarios,
        **kwargs,
    )


def stream(scenarios: tuple[ScenarioInstance, ...] = (), seed: int = 4100, **kwargs: Any):
    source = make_source(scenarios, seed, **kwargs)
    source.connect()
    source.start()
    samples = []
    while (s := source.read_measurements()) is not None:
        samples.append(s)
    source.disconnect()
    return samples


def analyses(model: AnomalyModel, samples: list[Sample]) -> list[dict[str, Any]]:
    builder, out = WindowBuilder(), []
    for s in samples:
        window = builder.push(s)
        if window is not None:
            out.append(model.infer(window))
    return out


def first_with(model: AnomalyModel, decision: str, samples: list[Sample]) -> dict[str, Any]:
    for result in analyses(model, samples):
        if result["decision"] == decision:
            return result
    raise AssertionError(f"no {decision} window in the stream")


def fixture_event(trigger_kind: str = "THERMAL_DEMO", trigger_ms: int = 67600) -> Event:
    samples = [
        Sample(
            "fixture",
            Source.SIMULATION,
            i,
            trigger_ms - 30000 + i * 200,
            {
                "COOLANT_TEMP": Reading(105.438 if i <= 150 else 123.965, "°C"),
                "SPEED": Reading(40, "km/h"),
            },
        )
        for i in range(301)
    ]
    return Event(
        "fixture-event",
        "fixture",
        Trigger(trigger_kind, "test", "test", "fixture-1", trigger_ms),
        samples,
        "COMPLETE",
        trigger_ms + 30000,
    )


class FakeRepo:
    """Duck-typed repository that records the AI linkage Session writes."""

    def __init__(self) -> None:
        self.links: list[tuple[str, str, int]] = []
        self.statuses: dict[str, dict[str, Any]] = {}
        self.saved: list[dict[str, Any]] = []

    def link_analysis(self, event_id: str, session_id: str, end_ms: int) -> None:
        self.links.append((event_id, session_id, end_ms))

    def save_event_ai_status(self, event_id: str, status: dict[str, Any]) -> None:
        self.statuses[event_id] = status

    def save_analysis(self, result: dict[str, Any]) -> None:
        self.saved.append(result)

    def save_event(self, event: Event) -> None:
        pass


class StubAnalyzer:
    def __init__(self, result: dict[str, Any] | None, max_age_ms: int = 2000) -> None:
        self.result, self.max_age_ms = result, max_age_ms
        self.model = SimpleNamespace(metadata={"model_version": "stub-1"})

    def latest_before(self, session_id: str, time_ms: int) -> dict[str, Any] | None:
        return self.result

    def explain(self, analysis: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("stub has no explainer")


def explained(model: AnomalyModel, result: dict[str, Any]) -> dict[str, Any]:
    return {**result, "xai": explain(model, result)}
