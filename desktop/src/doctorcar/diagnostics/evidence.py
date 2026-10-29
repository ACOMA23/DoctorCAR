from dataclasses import dataclass, field
from statistics import mean

from doctorcar.core.models import Event, Quality
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY
from doctorcar.core.simulation_profile import PROFILE
from doctorcar.monitoring.evidence_rules import (
    Finding,
    classify_sensors,
    evaluate_relations,
    valid_value,
)


@dataclass(frozen=True)
class MeasurementStatistics:
    unit: str
    count: int
    start_ms: int
    end_ms: int
    minimum: float
    maximum: float
    mean: float
    delta: float


@dataclass(frozen=True)
class Evidence:
    sources: tuple[str, ...]
    valid_temperature_count: int
    maximum_temperature: float | None
    dtcs: tuple[str, ...]
    invalid_reading_count: int
    has_freeze_frame: bool
    sample_count: int
    start_ms: int | None
    end_ms: int | None
    dtc_available: bool
    measurements: dict[str, MeasurementStatistics] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    sensor_states: dict[str, str] = field(default_factory=dict)
    calibrated_model: bool = False


def build_evidence(event: Event) -> Evidence:
    statistics = {}
    for sensor in NUMERIC_IDS:
        values = [
            (s.timestamp_ms, v) for s in event.samples if (v := valid_value(s, sensor)) is not None
        ]
        if values:
            numbers = [v for _, v in values]
            statistics[sensor] = MeasurementStatistics(
                REGISTRY.get(sensor).unit,
                len(values),
                values[0][0],
                values[-1][0],
                min(numbers),
                max(numbers),
                mean(numbers),
                numbers[-1] - numbers[0],
            )
    before_detection = tuple(
        s for s in event.samples if s.timestamp_ms <= event.trigger.timestamp_ms
    )
    findings = evaluate_relations(before_detection)
    temperatures = [
        r.value
        for s in event.samples
        if (r := s.readings.get("COOLANT_TEMP")) is not None
        and r.quality == Quality.AVAILABLE
        and r.value is not None
    ]
    return Evidence(
        tuple(sorted({s.source.value for s in event.samples})),
        len(temperatures),
        max(temperatures) if temperatures else None,
        tuple(
            sorted(
                {
                    code
                    for s in event.samples
                    if s.dtc_quality == Quality.AVAILABLE
                    for code in s.dtcs
                }
            )
        ),
        sum(r.quality != Quality.AVAILABLE for s in event.samples for r in s.readings.values()),
        any(s.freeze_frame is not None for s in event.samples),
        len(event.samples),
        event.samples[0].timestamp_ms if event.samples else None,
        event.samples[-1].timestamp_ms if event.samples else None,
        any(s.dtc_quality == Quality.AVAILABLE for s in event.samples),
        statistics,
        findings,
        classify_sensors(before_detection, findings),
        bool(event.samples and event.samples[0].provenance == PROFILE),
    )
