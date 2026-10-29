"""DC-FIX-001 Gate 3: DEF-004 (S04 masked by S07 flatline) and the S07 flatline gap of DEF-003."""

import pytest

from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.monitoring.evidence_rules import evaluate_relations, map_reference_frozen
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource

S04 = ScenarioInstance("S04", 60000, 18000, 1.0)
S07_FLAT = ScenarioInstance("S07", 60000, 18000, 0.85, "flatline")


def findings(scenarios=(), seed=4100, mode="FAULT_INJECTION"):
    kwargs = {"scenarios": tuple(scenarios)} if scenarios else {}
    src = SimulationSource(seed=seed, scenario_family="multisensor", mode=mode, **kwargs)
    src.connect()
    src.start()
    validator, buf, found = DataQualityValidator(), [], {}
    while not src.exhausted:
        sample = src.read_measurements()
        if sample is None:
            break
        buf.append(validator.validate_measurement(sample).sample)
        buf = [s for s in buf if sample.timestamp_ms - s.timestamp_ms <= 8000]
        for f in evaluate_relations(tuple(buf)):
            found.setdefault(f.rule_id, f)
    return found


def test_s07_flatline_alone_is_detected_even_in_a_steady_cruise():
    assert "MS_SIGNAL" in findings([S07_FLAT])


def test_s04_alone_unchanged():
    assert set(findings([S04])) == {"MS_AIRFLOW"}


def test_s04_is_not_masked_by_simultaneous_s07_flatline_and_says_why():
    found = findings([S04, S07_FLAT])
    assert {"MS_AIRFLOW", "MS_SIGNAL"} <= set(found)
    airflow = found["MS_AIRFLOW"]
    assert airflow.metrics["map_reference_frozen"] == 1.0
    assert any("MAP reference is unreliable" in c for c in airflow.contradicting_evidence)


@pytest.mark.parametrize("seed", [8000, 8001, 8002, 8003])
def test_no_rule_fires_on_healthy_trips(seed):
    assert findings(mode="NORMAL", seed=seed) == {}


def test_frozen_reference_is_not_claimed_when_map_follows_load():
    src = SimulationSource(seed=8000, scenario_family="multisensor", mode="NORMAL")
    src.connect()
    src.start()
    samples = []
    while not src.exhausted:
        s = src.read_measurements()
        if s is None:
            break
        samples.append(s)
        if len(samples) > 5 and s.timestamp_ms >= 20000:
            window = [x for x in samples if s.timestamp_ms - x.timestamp_ms <= 3000]
            assert not map_reference_frozen(window, s.timestamp_ms)
