from dataclasses import replace

import pytest

from doctorcar.core.models import Event, Quality, Reading, Trigger
from doctorcar.core.session import Session
from doctorcar.diagnostics.evidence import build_evidence
from doctorcar.diagnostics.hypotheses import evaluate_hypotheses
from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.monitoring.evidence_rules import classify_sensors, evaluate_relations
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def run(repo, scenarios=(), **kwargs):
    source = SimulationSource(
        scenario_family="multisensor",
        step_ms=1000,
        mode="FAULT_INJECTION" if scenarios else "NORMAL",
        scenarios=scenarios,
        **kwargs,
    )
    session = Session(source, repo)
    session.start()
    try:
        while not source.exhausted:
            session.step()
    finally:
        session.stop()
    return session


def normal_window():
    source = SimulationSource(scenario_family="multisensor", step_ms=1000)
    source.connect()
    source.start()
    samples = []
    while (s := source.read_measurements()) is not None:
        if 60_000 <= s.timestamp_ms <= 68_000:
            samples.append(s)
    source.stop()
    source.disconnect()
    return samples


def altered(samples, **changes):
    result = []
    for sample in samples:
        readings = dict(sample.readings)
        for key, value in changes.items():
            old = readings[key]
            readings[key] = Reading(
                value(old.value) if callable(value) else value,
                old.unit,
                Quality.MISSING if value is None else old.quality,
            )
        result.append(replace(sample, readings=readings))
    return tuple(result)


def test_ms01_normal_no_rules_false_alarm(tmp_path):
    with SQLiteRepository(tmp_path / "normal.db") as repo:
        run(repo)
        assert repo.list_events() == []


@pytest.mark.parametrize(
    "sid,kind",
    [
        ("S01", "MS_THERMAL"),
        ("S02", "MS_AIR_FUEL"),
        ("S03", "MS_FUEL_RESPONSE"),
        ("S04", "MS_AIRFLOW"),
        ("S05", "MS_SUPPLY"),
        ("S06", "MS_COMBUSTION"),
        ("S07", "MS_SIGNAL"),
    ],
)
def test_ms02_ms03_patterns_have_quantitative_evidence_alternatives_and_checks(tmp_path, sid, kind):
    with SQLiteRepository(tmp_path / (sid + ".db")) as repo:
        run(repo, (ScenarioInstance(sid),))
        matches = [r for r in repo.list_events() if r["kind"] == kind]
        assert matches, repo.list_events()
        event = repo.get_event(matches[0]["event_id"])
        evidence = build_evidence(event)
        finding = next(f for f in evidence.findings if f.rule_id == kind)
        assert len(finding.metrics) >= 3
        hypotheses = evaluate_hypotheses(event, evidence)
        assert len(hypotheses) >= 2
        assert all(
            h.supporting_evidence and h.missing_evidence and h.recommended_check for h in hypotheses
        )
        report = build_diagnostic_report(event)
        assert "الأدلة غير كافية لتحديد السبب المحتمل." in report
        assert "ثقة ميكانيكية معايرة" in report
        assert all(sid not in line for line in report.splitlines())
        assert event.status == "COMPLETE"
        assert event.samples[0].timestamp_ms == event.trigger.timestamp_ms - 30000
        assert event.samples[-1].timestamp_ms == event.trigger.timestamp_ms + 30000


def test_ms04_ms09_blind_values_not_labels_choose_pattern():
    samples = normal_window()
    intake = altered(
        samples, MAF=lambda x: x * 0.7, INTAKE_PRESSURE=lambda x: x + 12, SHORT_FUEL_TRIM=22
    )
    fuel = altered(samples, SHORT_FUEL_TRIM=22, LONG_FUEL_TRIM=12)
    assert {f.rule_id for f in evaluate_relations(intake)} == {"MS_AIR_FUEL"}
    assert {f.rule_id for f in evaluate_relations(fuel)} == {"MS_FUEL_RESPONSE"}
    # Deliberately misleading metadata cannot change a value-based conclusion.
    disguised = tuple(
        replace(s, phase="S03 wrong cause", raw={"scenario_id": "S05"}) for s in intake
    )
    assert evaluate_relations(disguised) == evaluate_relations(intake)
    r = evaluate_relations(intake)[0]
    assert r.metrics["stft_mean_pct"] == 22
    assert r.metrics["map_residual_kPa"] == pytest.approx(12, abs=0.001)
    assert r.metrics["maf_residual_pct"] == pytest.approx(-30, abs=0.01)


def test_ms05_voltage_requires_concurrent_evidence_and_transport_is_separate():
    samples = normal_window()
    voltage = altered(samples, CONTROL_MODULE_VOLTAGE=10.5)
    assert not any(f.rule_id == "MS_SUPPLY" for f in evaluate_relations(voltage))
    disturbed = altered(voltage, MAF=None)
    finding = next(f for f in evaluate_relations(disturbed) if f.rule_id == "MS_SUPPLY")
    assert finding.metrics["concurrent_low_voltage_missing_samples"] == 9
    zero_voltage = altered(disturbed, CONTROL_MODULE_VOLTAGE=0)
    zero_finding = next(f for f in evaluate_relations(zero_voltage) if f.rule_id == "MS_SUPPLY")
    assert zero_finding.metrics["voltage_min_V"] == 0
    event = Event(
        "transport",
        samples[0].session_id,
        Trigger("CONNECTION", "transport", "USB lost", "v1", 68000),
        list(voltage),
        "PARTIAL",
        68000,
    )
    assert not any(
        "دينمو" in h.description for h in evaluate_hypotheses(event, build_evidence(event))
    )


def test_ms06_intermittent_short_problem_recorded_after_recovery(tmp_path):
    with SQLiteRepository(tmp_path / "short.db") as repo:
        run(repo, (ScenarioInstance("S06", 60000, 9000),), duration_ms=115000)
        event = repo.get_event(
            next(r["event_id"] for r in repo.list_events() if r["kind"] == "MS_COMBUSTION")
        )
        assert 60000 < event.trigger.timestamp_ms < 69000
        assert event.end_ms == event.trigger.timestamp_ms + 30000 > 69000
        assert event.status == "COMPLETE"


def test_ms07_cycle_transition_does_not_restart_recorder(tmp_path):
    with SQLiteRepository(tmp_path / "overlap.db") as repo:
        session = run(
            repo,
            (ScenarioInstance("S01", 30000, 45000), ScenarioInstance("S02", 60000, 18000)),
            duration_ms=125000,
        )
        events = [
            repo.get_event(r["event_id"]) for r in repo.list_events() if r["kind"].startswith("MS_")
        ]
        assert len(events) >= 2
        assert all(e.session_id == session.last_sample.session_id for e in events)
        assert all(
            e.status == "COMPLETE" and e.end_ms == e.trigger.timestamp_ms + 30000 for e in events
        )
        assert any(e.trigger.timestamp_ms < 60000 < e.end_ms for e in events)


@pytest.mark.parametrize(
    "quality", [Quality.MISSING, Quality.INVALID, Quality.STALE, Quality.UNSUPPORTED]
)
def test_ms11_missing_reference_suppresses_unsupported_air_diagnosis(quality):
    samples = altered(normal_window(), MAF=lambda x: x * 0.6)
    incomplete = []
    for sample in samples:
        readings = dict(sample.readings)
        readings["INTAKE_PRESSURE"] = Reading(None, "kPa", quality)
        incomplete.append(replace(sample, readings=readings))
    findings = evaluate_relations(tuple(incomplete))
    assert not any(f.rule_id in ("MS_AIRFLOW", "MS_AIR_FUEL", "MS_FUEL_RESPONSE") for f in findings)
    assert classify_sensors(tuple(incomplete), findings)["MAF"] == "UNRESOLVED"


def test_flatline_requires_dynamic_references_and_quality_is_separate():
    dynamic = normal_window()
    source = SimulationSource(scenario_family="multisensor", step_ms=1000)
    source.connect()
    source.start()
    dynamic = []
    while (sample := source.read_measurements()) is not None:
        if 45000 <= sample.timestamp_ms <= 53000:
            dynamic.append(sample)
    source.stop()
    source.disconnect()
    flat = altered(dynamic, INTAKE_PRESSURE=45)
    findings = evaluate_relations(flat)
    assert any(f.rule_id == "MS_SIGNAL" for f in findings)
    assert (
        classify_sensors(flat, findings)["INTAKE_PRESSURE"] == "SIGNAL_LOSS_OR_SUSPECTED_FLATLINE"
    )
    assert flat[-1].readings["INTAKE_PRESSURE"].quality == Quality.AVAILABLE
    steady = altered(flat, RPM=1500, MAF=5, ENGINE_LOAD=20)
    assert not any(f.rule_id == "MS_SIGNAL" for f in evaluate_relations(steady))


def test_ms09_ms12_statistics_reload_and_no_future_evidence(tmp_path):
    path = tmp_path / "report.db"
    with SQLiteRepository(path) as repo:
        run(repo, (ScenarioInstance("S02"),))
        event = repo.get_event(
            next(r["event_id"] for r in repo.list_events() if r["kind"] == "MS_AIR_FUEL")
        )
        evidence = build_evidence(event)
        values = [s.readings["MAF"].value for s in event.samples]
        assert evidence.measurements["MAF"].minimum == min(values)
        assert evidence.measurements["MAF"].maximum == max(values)
        post = [
            replace(s, readings={**s.readings, "MAF": Reading(99, "g/s")})
            if s.timestamp_ms > event.trigger.timestamp_ms
            else s
            for s in event.samples
        ]
        assert build_evidence(replace(event, samples=post)).findings == evidence.findings
        report = build_diagnostic_report(event)
        report_en = build_diagnostic_report(event, "en")
        for heading in "ABCDEFGHIJK":
            assert heading + "." in report_en
        assert "95%" not in report_en
    with SQLiteRepository(path) as repo:
        assert build_diagnostic_report(repo.get_event(event.event_id)) == report


def test_units_invalid_and_unknown_calibration_do_not_produce_findings():
    samples = altered(normal_window(), MAF=lambda x: x * 0.6)
    assert any(f.rule_id == "MS_AIRFLOW" for f in evaluate_relations(samples))
    assert not evaluate_relations(tuple(replace(s, provenance="unknown") for s in samples))
    broken = tuple(replace(s, readings={**s.readings, "MAF": Reading(1, "wrong")}) for s in samples)
    assert not evaluate_relations(broken)
    gaps = tuple(replace(s, timestamp_ms=s.timestamp_ms * 2) for s in samples)
    assert not evaluate_relations(gaps)
