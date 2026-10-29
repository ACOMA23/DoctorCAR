"""DC-FIX-001 Gate 1: DEF-007 (no bound outside simulation) and DEF-013 (unknown sensor)."""

import json
import math

import pytest

from doctorcar.core.models import Quality, Reading, Sample, Source
from doctorcar.core.session import Session
from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.sources.replay import ReplaySource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def make(source, readings, seq=0, provenance=None):
    base = {"RPM": Reading(1500, "rpm"), "COOLANT_TEMP": Reading(90, "°C")}
    base.update(readings)
    return Sample("trip", source, seq, seq * 200, base, provenance=provenance)


@pytest.mark.parametrize("source", list(Source))
@pytest.mark.parametrize(
    ("sensor", "unit", "value"),
    [
        ("RPM", "rpm", 1e308),
        ("RPM", "rpm", -5),
        ("SPEED", "km/h", 5000),
        ("MAF", "g/s", 1e9),
        ("INTAKE_PRESSURE", "kPa", -300),
        ("SHORT_FUEL_TRIM", "%", 900),
        ("COOLANT_TEMP", "°C", 1e6),
    ],
)
def test_implausible_value_is_invalid_for_every_source(source, sensor, unit, value):
    result = DataQualityValidator().validate_measurement(
        make(source, {sensor: Reading(value, unit)})
    )
    reading = result.sample.readings[sensor]
    assert reading.quality == Quality.INVALID
    assert any(i.startswith("implausible") and i.endswith(sensor) for i in result.issues)
    assert "invalid_reading" in result.issues
    # the raw value is kept for diagnostics, but never as AVAILABLE
    assert reading.value == value


@pytest.mark.parametrize("value", [0, 800, 6500, 20000])
def test_plausible_rpm_stays_available_for_replay(value):
    result = DataQualityValidator().validate_measurement(
        make(Source.REPLAY, {"RPM": Reading(value, "rpm")})
    )
    assert result.sample.readings["RPM"].quality == Quality.AVAILABLE
    assert not any(i.startswith("implausible") for i in result.issues)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_cannot_be_constructed(bad):
    with pytest.raises(ValueError):
        Reading(bad, "rpm")


def test_unknown_sensor_is_dropped_but_kept_in_raw_and_reported():
    sample = make(Source.REPLAY, {"FOO": Reading(1, "x")})
    result = DataQualityValidator().validate_measurement(sample)
    assert "FOO" not in result.sample.readings
    assert "unknown_sensor:FOO" in result.issues
    assert result.accepted
    assert result.sample.raw["readings"]["FOO"]["value"] == 1
    # an unknown sensor is not a data-quality INVALID of a known one
    assert "invalid_reading" not in result.issues


def test_known_sensor_with_unfamiliar_name_case_is_not_rejected_as_invalid():
    result = DataQualityValidator().validate_measurement(make(Source.REPLAY, {}))
    assert all(r.quality != Quality.INVALID for r in result.sample.readings.values())


def test_replay_session_stores_implausible_value_as_invalid_and_not_unknown(tmp_path):
    path = tmp_path / "trip.jsonl"
    rows = []
    for i in range(3):
        s = make(Source.REPLAY, {"FOO": Reading(1, "x")}, seq=i)
        d = s.to_dict()
        if i == 1:
            d["readings"]["RPM"]["value"] = 1e308
        rows.append(json.dumps(d))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with SQLiteRepository(tmp_path / "t.sqlite3") as repo:
        source = ReplaySource(path)
        source.verify()
        session = Session(source, repo)
        session.start()
        results = [session.step() for _ in range(3)]
        session.stop()
    got = [r.sample.readings for r in results if r]
    assert got and all("FOO" not in r for r in got)
    assert any(r["RPM"].quality == Quality.INVALID for r in got)
