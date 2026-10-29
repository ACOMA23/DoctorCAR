"""DC-FIX-001 Gate 4: DEF-006 the engine must not stay parked after ~150 s in long sessions."""

import pytest

from doctorcar.core.session import Session
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def samples(**kwargs):
    src = SimulationSource(**kwargs)
    src.connect()
    src.start()
    out = []
    while not src.exhausted:
        s = src.read_measurements()
        if s is None:
            break
        out.append(s)
    return out


def test_default_trip_keeps_its_natural_parked_ending():
    rows = samples(seed=4100, scenario_family="multisensor", mode="NORMAL")
    assert len(rows) == 776
    assert rows[-1].phase == "محرك متوقف" and rows[-1].readings["RPM"].value == 0


def test_long_session_keeps_driving_with_a_continuous_clock():
    rows = samples(seed=4100, scenario_family="multisensor", mode="NORMAL", duration_ms=600_000)
    assert len(rows) == 3001
    assert [r.timestamp_ms for r in rows] == [i * 200 for i in range(3001)]
    assert all(r.readings["RPM"].value > 0 for r in rows)  # never parked
    assert max(r.readings["SPEED"].value for r in rows if r.timestamp_ms > 300_000) > 50
    assert not any(r.phase == "محرك متوقف" for r in rows)
    # no discontinuity larger than the cycle itself allows between consecutive samples
    jumps = [
        abs(b.readings["SPEED"].value - a.readings["SPEED"].value)
        for a, b in zip(rows, rows[1:], strict=False)
    ]
    assert max(jumps) < 3.0


@pytest.mark.parametrize("duration_ms", [155_001, 300_000])
def test_values_stay_inside_plausible_bounds(duration_ms):
    from doctorcar.monitoring.data_quality import DataQualityValidator

    validator = DataQualityValidator()
    for s in samples(
        seed=11, scenario_family="multisensor", mode="NORMAL", duration_ms=duration_ms
    ):
        r = validator.validate_measurement(s)
        assert not any(i.startswith(("implausible", "invalid")) for i in r.issues)


def test_fault_after_150_s_is_still_detected_in_a_long_session(tmp_path):
    src = SimulationSource(
        seed=4100,
        scenario_family="multisensor",
        mode="FAULT_INJECTION",
        duration_ms=400_000,
        scenarios=(ScenarioInstance("S04", 165_000, 35_000, 1.0),),
    )
    with SQLiteRepository(tmp_path / "long.sqlite3") as repo:
        session = Session(src, repo)
        session.start()
        while not src.exhausted:
            session.step()
        session.stop()
        kinds = {
            (r["kind"], r["status"]) for r in repo.list_events() if r["kind"] != "DATA_QUALITY"
        }
    assert ("MS_AIRFLOW", "COMPLETE") in kinds


def test_manual_stop_mid_trip_finalizes_open_events_as_partial(tmp_path):
    src = SimulationSource(
        seed=4100,
        scenario_family="multisensor",
        mode="FAULT_INJECTION",
        duration_ms=400_000,
        scenarios=(ScenarioInstance("S04", 165_000, 35_000, 1.0),),
    )
    with SQLiteRepository(tmp_path / "stop.sqlite3") as repo:
        session = Session(src, repo)
        session.start()
        for _ in range(int(175_000 / 200)):
            session.step()
        session.stop()
        rows = [r for r in repo.list_events() if r["kind"] != "DATA_QUALITY"]
        assert rows and all(r["status"] in ("PARTIAL", "COMPLETE") for r in rows)
