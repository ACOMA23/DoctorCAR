import json
from dataclasses import replace

import pytest

from doctorcar.core.models import Quality, Reading, Sample, Source
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY, SensorSpec
from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.sources.replay import ReplaySource
from doctorcar.sources.simulation import SimulationSource


def collect(scenario="normal", seed=42):
    source = SimulationSource(scenario, seed=seed, step_ms=1000)
    source.connect()
    source.start()
    samples = []
    while (sample := source.read_measurements()) is not None:
        samples.append(sample)
    source.stop()
    source.disconnect()
    return samples


def test_registry():
    assert len(NUMERIC_IDS) == 11
    assert REGISTRY.get("DTC").kind == "diagnostic"
    assert REGISTRY.get("RPM").valid_range is None
    assert [s.sensor_id for s in REGISTRY.get_supported_sensors({"RPM"})] == ["RPM"]
    with pytest.raises(ValueError):
        REGISTRY.register_sensor(SensorSpec("RPM", "مكرر", "rpm", "rpm"))


@pytest.mark.parametrize("value", [True, "12", float("nan"), float("inf")])
def test_bad_reading_types(value):
    with pytest.raises(ValueError):
        Reading(value, "rpm")


@pytest.mark.parametrize(
    "field,value",
    [("timestamp_ms", -1), ("sequence_number", True), ("session_id", ""), ("source", "REAL")],
)
def test_invalid_sample(field, value):
    sample = collect()[0]
    with pytest.raises(ValueError):
        replace(sample, **{field: value})


def test_round_trip_and_required_fields():
    sample = collect()[0]
    assert Sample.from_dict(json.loads(json.dumps(sample.to_dict()))) == sample
    data = sample.to_dict()
    del data["timestamp_ms"]
    with pytest.raises(KeyError):
        Sample.from_dict(data)


def test_deterministic_time_dependent_correlated_simulation():
    a, b, c = collect(), collect(), collect(seed=9)
    assert [s.readings for s in a] == [s.readings for s in b]
    assert a[50].readings != c[50].readings
    assert {s.phase for s in a} == {
        "بدء المحرك",
        "إحماء",
        "خمول",
        "تسارع",
        "سير مستقر",
        "تباطؤ",
        "محرك متوقف",
    }
    assert all(s.source == Source.SIMULATION and not s.dtcs for s in a)
    assert a[59].readings["SPEED"].value > a[46].readings["SPEED"].value
    assert a[59].readings["RPM"].value > a[46].readings["RPM"].value
    assert a[30].readings["COOLANT_TEMP"].value > a[0].readings["COOLANT_TEMP"].value
    assert a[-1].readings["RPM"].value == 0
    assert max(s.readings["COOLANT_TEMP"].value for s in collect("thermal")) > 110


def test_quality_preserves_raw_and_checks_unit_missing_unsupported():
    sample = collect()[0]
    readings = dict(sample.readings)
    readings["RPM"] = Reading(10, "wrong")
    readings["MAF"] = Reading(None, "g/s", Quality.UNSUPPORTED)
    del readings["SPEED"]
    result = DataQualityValidator().validate_measurement(replace(sample, readings=readings))
    assert result.accepted
    assert result.sample.readings["RPM"].quality == Quality.INVALID
    assert result.sample.raw["readings"]["RPM"]["unit"] == "wrong"
    assert result.sample.readings["SPEED"].value is None
    assert result.sample.readings["MAF"].quality == Quality.UNSUPPORTED


def test_time_age_order_duplicate_and_gap():
    sample = collect()[0]
    validator = DataQualityValidator()
    assert validator.validate_measurement(sample).accepted
    assert not validator.validate_measurement(sample).accepted
    assert not validator.validate_measurement(replace(sample, sequence_number=1)).accepted
    result = validator.validate_measurement(
        replace(sample, sequence_number=3, timestamp_ms=2000), now_ms=6000
    )
    assert "sequence_gap" in result.issues and "stale" in result.issues
    assert result.sample.readings["RPM"].quality == Quality.STALE
    assert not validator.validate_measurement(
        replace(sample, sequence_number=4, timestamp_ms=9000), now_ms=6000
    ).accepted


def test_demo_invalid_value_flagged_without_inventing_zero():
    sample = collect("invalid")[73]
    result = DataQualityValidator().validate_measurement(sample)
    assert result.sample.readings["COOLANT_TEMP"].quality == Quality.INVALID
    assert result.sample.readings["COOLANT_TEMP"].value == -999


def test_replay_lifecycle_provenance_and_closing(tmp_path):
    path = tmp_path / "trip.jsonl"
    original = collect()[:3]
    path.write_text("".join(json.dumps(s.to_dict()) + "\n" for s in original), encoding="utf-8")
    source = ReplaySource(path)
    source.connect()
    source.start()
    replay = [source.read_measurements() for _ in original]
    assert replay[0].source == Source.REPLAY
    assert replay[0].provenance == "SIMULATION"
    assert replay[0].session_id != original[0].session_id
    assert [s.timestamp_ms for s in replay] == [s.timestamp_ms for s in original]
    assert source.read_measurements() is None and source.exhausted
    source.stop()
    source.disconnect()
    assert source._file is None
    source.connect()
    source.disconnect()


def test_source_requires_connection():
    with pytest.raises(RuntimeError):
        SimulationSource().start()
