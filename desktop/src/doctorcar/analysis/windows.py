"""Causal windows. Only numeric readings, units, quality, identity and time enter ML."""

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from doctorcar.core.models import Sample
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY
from doctorcar.monitoring.evidence_rules import valid_value

SCHEMA_VERSION = "timeseries-1"
FEATURE_NAMES = tuple(
    f"{s}.{stat}" for s in NUMERIC_IDS for stat in ("mean", "std", "slope", "coverage")
) + ("MAF.relative_residual", "INTAKE_PRESSURE.residual", "RPM.trim_correlation")


@dataclass(frozen=True)
class WindowConfig:
    length_ms: int = 5000
    stride_ms: int = 1000
    sampling_ms: int = 200
    minimum_coverage: float = 0.8

    def __post_init__(self) -> None:
        if self.length_ms < 1000 or self.stride_ms < 1 or self.sampling_ms < 1:
            raise ValueError("Invalid window timing")
        if not 0.5 <= self.minimum_coverage <= 1 or self.length_ms / self.sampling_ms > 2000:
            raise ValueError("Invalid coverage or excessive window size")


DEFAULT_CONFIG = WindowConfig()
FEATURE_UNITS = tuple(
    "ratio" if stat == "coverage" else REGISTRY.get(sensor).unit + ("/s" if stat == "slope" else "")
    for sensor in NUMERIC_IDS
    for stat in ("mean", "std", "slope", "coverage")
) + ("ratio", "kPa", "correlation")


def extract(samples: tuple[Sample, ...], config: WindowConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    if not samples:
        return {"decision": "INSUFFICIENT_DATA", "reason": "empty"}
    end = samples[-1]
    samples = tuple(s for s in samples if s.timestamp_ms >= end.timestamp_ms - config.length_ms)
    status: dict[str, Any] = {
        "decision": "INSUFFICIENT_DATA",
        "start_ms": samples[0].timestamp_ms,
        "end_ms": end.timestamp_ms,
        "session_id": end.session_id,
        "feature_schema": SCHEMA_VERSION,
    }
    if (
        len(samples) < 3
        or end.timestamp_ms - samples[0].timestamp_ms < config.length_ms
        or any(s.session_id != end.session_id or s.source != end.source for s in samples)
        or any(
            b.sequence_number != a.sequence_number + 1
            or not 0 < b.timestamp_ms - a.timestamp_ms <= config.sampling_ms * 1.5
            for a, b in zip(samples, samples[1:], strict=False)
        )
    ):
        return {**status, "reason": "time/session/sequence_gap"}
    times = np.array([s.timestamp_ms / 1000 for s in samples])
    columns = {
        sensor: np.array(
            [
                valid_value(s, sensor) if valid_value(s, sensor) is not None else np.nan
                for s in samples
            ]
        )
        for sensor in NUMERIC_IDS
    }
    features: list[float] = []
    coverage = {}
    for sensor, values in columns.items():
        mask = np.isfinite(values)
        ratio = float(mask.mean())
        coverage[sensor] = ratio
        if ratio < config.minimum_coverage:
            return {**status, "reason": "sensor_coverage", "coverage": coverage}
        # Missing/stale/unsupported rows are omitted, never filled with zero or future values.
        x, y = times[mask], values[mask]
        slope = float(np.polyfit(x - x[0], y, 1)[0])
        features.extend((float(y.mean()), float(y.std()), slope, ratio))
    rpm, load, maf, pressure = (
        columns[k] for k in ("RPM", "ENGINE_LOAD", "MAF", "INTAKE_PRESSURE")
    )
    expected = rpm * (0.002 + 0.00008 * load)
    features.append(float(np.nanmean((maf - expected) / np.maximum(expected, 1))))
    features.append(float(np.nanmean(pressure - np.where(rpm > 0, 30 + 0.65 * load, 100))))
    trim = columns["SHORT_FUEL_TRIM"]
    mask = np.isfinite(rpm) & np.isfinite(trim)
    corr = (
        float(np.corrcoef(rpm[mask], trim[mask])[0, 1])
        if np.std(rpm[mask]) > 1e-6 and np.std(trim[mask]) > 1e-6
        else 0.0
    )
    features.append(corr)
    return {
        **status,
        "decision": "READY",
        "features": features,
        "feature_names": list(FEATURE_NAMES),
        "feature_units": list(FEATURE_UNITS),
        "coverage": coverage,
    }


class WindowBuilder:
    def __init__(self, config: WindowConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.samples: deque[Sample] = deque(maxlen=int(config.length_ms / config.sampling_ms) + 2)
        self.last_end: int | None = None

    def push(self, sample: Sample) -> dict[str, Any] | None:
        if self.samples and (
            sample.session_id != self.samples[-1].session_id
            or sample.source != self.samples[-1].source
            or sample.timestamp_ms <= self.samples[-1].timestamp_ms
        ):
            self.samples.clear()
            self.last_end = None
        self.samples.append(sample)
        while (
            self.samples
            and sample.timestamp_ms - self.samples[0].timestamp_ms > self.config.length_ms
        ):
            self.samples.popleft()
        if (
            self.last_end is not None
            and sample.timestamp_ms - self.last_end < self.config.stride_ms
        ):
            return None
        self.last_end = sample.timestamp_ms
        return extract(tuple(self.samples), self.config)
