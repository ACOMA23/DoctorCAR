import pytest

from doctorcar.core.simulation_profile import PROFILE
from doctorcar.sources.scenarios import SCENARIOS_MS, ScenarioInstance, scenario_schedule
from doctorcar.sources.simulation import SimulationSource


def collect(**kwargs):
    source = SimulationSource(scenario_family="multisensor", step_ms=1000, **kwargs)
    source.connect()
    source.start()
    samples = []
    try:
        while (sample := source.read_measurements()) is not None:
            samples.append(sample)
    finally:
        source.stop()
        source.disconnect()
    return samples, source.get_simulation_metadata()


@pytest.mark.parametrize("scenario_id", list(SCENARIOS_MS))
def test_correlated_effects_recover_without_truth_in_samples(scenario_id):
    normal, _ = collect(mode="NORMAL")
    values, metadata = collect(mode="FAULT_INJECTION", scenarios=(ScenarioInstance(scenario_id),))
    assert normal[59].readings == values[59].readings
    assert normal[100].readings == values[100].readings
    assert any(a.readings != b.readings for a, b in zip(normal[60:95], values[60:95], strict=True))
    assert all(s.provenance == PROFILE for s in values)
    assert all(scenario_id not in str(s.to_dict()) for s in values)
    assert all(not s.dtcs and s.freeze_frame is None for s in values)
    assert metadata["scenario_schedule"][0]["scenario_id"] == scenario_id
    definition = SCENARIOS_MS[scenario_id]
    assert definition.relationships and definition.operating_conditions
    assert definition.alternative_hypotheses and definition.recommended_checks


def test_ms08_seed_schedule_data_overlap_and_long_duration():
    a, ma = collect(mode="RANDOM_FAULTS", seed=83)
    b, mb = collect(mode="RANDOM_FAULTS", seed=83)
    assert ma == mb and [s.readings for s in a] == [s.readings for s in b]
    assert [c["start_ms"] for c in ma["scenario_cycles"]][:4] == [30000, 60000, 90000, 120000]
    durations = set()
    for seed in range(25):
        schedule, _ = scenario_schedule(seed, 155000, 3, 0)
        durations.update(s.duration_ms for s in schedule)
    assert min(durations) < 30000 < max(durations)
    collect(mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S01"), ScenarioInstance("S02")))
    with pytest.raises(ValueError, match="Conflicting"):
        collect(
            mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02"), ScenarioInstance("S03"))
        )


def test_effect_is_context_dependent_and_intermittent():
    samples, _ = collect(mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S06"),))
    normal, _ = collect(mode="NORMAL")
    assert samples[61].readings["RPM"] != normal[61].readings["RPM"]
    assert samples[64].readings == normal[64].readings
    assert samples[67].readings["RPM"] != normal[67].readings["RPM"]
    early, _ = collect(mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02", 35000, 10000),))
    late, _ = collect(mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02", 60000, 10000),))
    early_delta = (
        early[39].readings["SHORT_FUEL_TRIM"].value - normal[39].readings["SHORT_FUEL_TRIM"].value
    )
    late_delta = (
        late[64].readings["SHORT_FUEL_TRIM"].value - normal[64].readings["SHORT_FUEL_TRIM"].value
    )
    assert early_delta > late_delta
