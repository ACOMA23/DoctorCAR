"""No correction discards the original sample. Rejected samples never enter the stream."""

from dataclasses import dataclass, replace

from doctorcar.core.models import Quality, Reading, Sample
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY

# Broad demonstration plausibility bounds, not diagnostic/vehicle specifications.
DEMO_BOUNDS = {
    "RPM": (0, 10000),
    "SPEED": (0, 300),
    "COOLANT_TEMP": (-40, 180),
    "ENGINE_LOAD": (0, 100),
    "THROTTLE_POS": (0, 100),
    "CONTROL_MODULE_VOLTAGE": (0, 32),
}

# Source-independent physical limits (DEF-007). Deliberately wide: they reject values that no
# sensor of this kind can report (e.g. RPM=1e308) without judging whether the value is healthy.
PHYSICAL_BOUNDS = {
    "RPM": (0, 20000),
    "SPEED": (0, 400),
    "COOLANT_TEMP": (-60, 300),
    "ENGINE_LOAD": (0, 100),
    "THROTTLE_POS": (0, 100),
    "INTAKE_PRESSURE": (0, 700),
    "MAF": (0, 2000),
    "INTAKE_TEMP": (-60, 300),
    "SHORT_FUEL_TRIM": (-100, 100),
    "LONG_FUEL_TRIM": (-100, 100),
    "CONTROL_MODULE_VOLTAGE": (0, 70),
}


@dataclass(frozen=True)
class ValidationResult:
    sample: Sample
    issues: tuple[str, ...]
    accepted: bool


class DataQualityValidator:
    def __init__(self, max_age_ms: int = 3000) -> None:
        self.max_age_ms = max_age_ms
        self.last: dict[tuple[str, str], tuple[int, int]] = {}

    def validate_measurement(self, sample: Sample, now_ms: int | None = None) -> ValidationResult:
        issues: list[str] = []
        key = (sample.session_id, sample.source.value)
        previous = self.last.get(key)
        if previous:
            seq, timestamp = previous
            if sample.sequence_number <= seq:
                return ValidationResult(sample, ("duplicate_or_reversed_sequence",), False)
            if sample.timestamp_ms <= timestamp:
                return ValidationResult(sample, ("nonincreasing_timestamp",), False)
            if sample.sequence_number > seq + 1:
                issues.append("sequence_gap")
        stale = now_ms is not None and now_ms - sample.timestamp_ms > self.max_age_ms
        if now_ms is not None and sample.timestamp_ms > now_ms + 1000:
            return ValidationResult(sample, ("future_timestamp",), False)
        readings = dict(sample.readings)
        demo = sample.source.value in ("SIMULATION", "DEVICE_TEST") or sample.provenance in (
            "SIMULATION",
            "DEVICE_TEST",
        )
        for sensor_id in NUMERIC_IDS:
            spec = REGISTRY.get(sensor_id)
            r = readings.get(sensor_id, Reading(None, spec.unit, Quality.MISSING))
            if r.quality == Quality.UNSUPPORTED:
                r = Reading(None, spec.unit, Quality.UNSUPPORTED)
            elif r.value is None:
                issues.append(f"missing:{sensor_id}")
                r = Reading(None, spec.unit, Quality.MISSING)
            elif r.unit != spec.unit:
                issues.append(f"unit:{sensor_id}")
                r = Reading(None, spec.unit, Quality.INVALID)
            elif (
                demo
                and sensor_id in DEMO_BOUNDS
                and r.value is not None
                and not (DEMO_BOUNDS[sensor_id][0] <= r.value <= DEMO_BOUNDS[sensor_id][1])
            ):
                issues.append(f"implausible_demo:{sensor_id}")
                r = replace(r, quality=Quality.INVALID)
            elif (
                sensor_id in PHYSICAL_BOUNDS
                and r.value is not None
                and not (PHYSICAL_BOUNDS[sensor_id][0] <= r.value <= PHYSICAL_BOUNDS[sensor_id][1])
            ):
                issues.append(f"implausible:{sensor_id}")
                r = replace(r, quality=Quality.INVALID)
            elif stale:
                r = replace(r, quality=Quality.STALE)
            readings[sensor_id] = r
        for sensor_id in sorted(set(readings) - set(NUMERIC_IDS)):
            # UNKNOWN is not INVALID: the identifier is not in the registry, so the value cannot
            # be interpreted. Drop it from the normalized stream (as network/serial receivers do)
            # but keep it in `raw` and report a quality issue (DEF-013).
            issues.append(f"unknown_sensor:{sensor_id}")
            del readings[sensor_id]
        if stale:
            issues.append("stale")
        if any(r.quality == Quality.INVALID for r in readings.values()):
            issues.append("invalid_reading")
        self.last[key] = sample.sequence_number, sample.timestamp_ms
        normalized = replace(sample, readings=readings, raw=sample.raw or sample.to_dict())
        return ValidationResult(normalized, tuple(issues), True)
