import pytest

from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.monitoring.event_detector import EventDetector
from doctorcar.sources.faults import FAULTS, FaultInstance, random_schedule
from doctorcar.sources.simulation import SimulationSource


def samples(source):
    source.connect()
    source.start()
    result = []
    while (sample := source.read_measurements()) is not None:
        result.append(sample)
    source.stop()
    source.disconnect()
    return result


def test_at001_normal_has_no_injection_or_false_alarm():
    source = SimulationSource(mode="NORMAL", step_ms=1000)
    validator, detector = DataQualityValidator(), EventDetector()
    for sample in samples(source):
        result = validator.validate_measurement(sample)
        assert not detector.evaluate_trigger(result.sample, result.issues)
    assert source.schedule == ()


def test_at003_at004_periodic_deterministic_schedule():
    a = SimulationSource(mode="RANDOM_FAULTS", seed=73, step_ms=1000)
    b = SimulationSource(mode="RANDOM_FAULTS", seed=73, step_ms=1000)
    c = SimulationSource(mode="RANDOM_FAULTS", seed=74, step_ms=1000)
    assert a.schedule == b.schedule and a.schedule != c.schedule
    assert [x["start_ms"] for x in a.cycles][:4] == [30000, 60000, 90000, 120000]
    assert [s.readings for s in samples(a)] == [s.readings for s in samples(b)]
    for seed in range(30):
        schedule, cycles = random_schedule(seed, 155000)
        assert all(0 <= len(c["fault_ids"]) <= 3 for c in cycles)
        assert all(0.1 <= f.severity <= 1 for f in schedule)


@pytest.mark.parametrize("fault_id", list(FAULTS))
def test_fault_definitions_and_signal_changes(fault_id):
    definition = FAULTS[fault_id]
    fault = FaultInstance(fault_id, 60000, definition.default_duration_ms)
    baseline = samples(SimulationSource(step_ms=1000))
    injected = samples(SimulationSource(mode="FAULT_INJECTION", faults=(fault,), step_ms=1000))
    assert baseline[59].readings == injected[59].readings
    assert baseline[85].readings == injected[85].readings
    assert any(
        a.readings != b.readings for a, b in zip(baseline[60:80], injected[60:80], strict=True)
    )
    assert definition.arabic_name and definition.english_name and definition.merge_rule
    assert not any(fault_id in str(s.to_dict()) for s in injected)


def test_at005_multiple_faults_and_conflicting_configuration():
    faults = (
        FaultInstance("thermal_sudden"),
        FaultInstance("low_voltage"),
        FaultInstance("maf_bias"),
    )
    output = samples(SimulationSource(mode="FAULT_INJECTION", faults=faults, step_ms=1000))
    assert output[60].readings["COOLANT_TEMP"].value >= 110
    assert output[60].readings["CONTROL_MODULE_VOLTAGE"].value < 10
    assert output[65].readings["COOLANT_TEMP"].value < 108
    with pytest.raises(ValueError):
        SimulationSource(
            mode="FAULT_INJECTION", faults=(faults[0], FaultInstance("sensor_dropout"))
        )


def test_intermittent_pattern_returns_and_disappears():
    normal = samples(SimulationSource(step_ms=1000))
    injected = samples(
        SimulationSource(
            mode="FAULT_INJECTION",
            step_ms=1000,
            faults=(FaultInstance("misfire_pattern", 60000, 12000),),
        )
    )
    assert injected[60].readings["RPM"] != normal[60].readings["RPM"]
    assert injected[61].readings["RPM"] == normal[61].readings["RPM"]
    assert injected[62].readings["RPM"] != normal[62].readings["RPM"]
