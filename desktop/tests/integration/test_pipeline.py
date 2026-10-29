from dataclasses import replace

import pytest

from doctorcar.core.models import Event, Quality, Reading, Trigger
from doctorcar.core.session import Session
from doctorcar.diagnostics.evidence import build_evidence
from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def run(repo, scenario):
    source = SimulationSource(scenario, step_ms=1000)
    session = Session(source, repo)
    session.start()
    while not source.exhausted:
        session.step()
    session.stop()
    return session


def test_simulation_pipeline_event_storage_report_reload(tmp_path):
    path = tmp_path / "pipeline.db"
    with SQLiteRepository(path) as repo:
        session = run(repo, "thermal")
        assert session.accepted == 156 and session.rejected == 0
        rows = repo.list_events()
        assert len(rows) == 1
        event = repo.get_event(rows[0]["event_id"])
        assert event.status == "COMPLETE"
        assert event.samples[0].timestamp_ms == event.trigger.timestamp_ms - 30000
        assert event.samples[-1].timestamp_ms == event.trigger.timestamp_ms + 30000
        report = build_diagnostic_report(event)
        assert "لا يوجد رمز مؤكد" in report
        assert "ليست ECU Freeze Frame" in report
        repo.export_session(event.session_id, tmp_path / "replay.jsonl")
    with SQLiteRepository(path) as repo:
        assert build_diagnostic_report(repo.get_event(rows[0]["event_id"])) == report


def test_normal_has_no_spurious_thermal_event_and_restart(tmp_path):
    with SQLiteRepository(tmp_path / "normal.db") as repo:
        session = run(repo, "normal")
        assert repo.list_events() == []
        previous = session.last_sample.session_id
        session.start()
        session.step()
        assert session.last_sample.session_id != previous
        session.stop()
        assert session.source.state == "DISCONNECTED"


def test_invalid_reading_is_quality_event_without_definitive_part(tmp_path):
    with SQLiteRepository(tmp_path / "invalid.db") as repo:
        run(repo, "invalid")
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert event.trigger.kind == "DATA_QUALITY"
        assert "الأدلة غير كافية" in build_diagnostic_report(event)
        assert build_evidence(event).invalid_reading_count > 0


def test_missing_contradictory_evidence_never_invents_temperature():
    source = SimulationSource()
    source.connect()
    source.start()
    sample = source.read_measurements()
    sample = replace(sample, readings={"COOLANT_TEMP": Reading(None, "°C", Quality.MISSING)})
    event = Event(
        "test",
        sample.session_id,
        Trigger("THERMAL_DEMO", "حرارة", "تجربة", "v1", 0),
        [sample],
        "PARTIAL",
        0,
    )
    assert build_evidence(event).maximum_temperature is None
    assert "الأدلة غير كافية" in build_diagnostic_report(event)
    assert "أعلى حرارة صالحة متاحة: غير متاحة" in build_diagnostic_report(event)
    source.disconnect()


def test_connection_loss_is_transport_not_vehicle_diagnosis(tmp_path):
    with SQLiteRepository(tmp_path / "connection.db") as repo:
        source = SimulationSource()
        session = Session(source, repo)
        session.start()
        session.step()
        session.record_connection_loss("انقطاع كابل اختباري")
        session.stop()
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert event.trigger.kind == "CONNECTION"
        assert event.status == "PARTIAL"
        assert "لا تستنتج عطل كهرباء المركبة" in build_diagnostic_report(event)


def test_source_resources_released_even_if_checkpoint_fails(tmp_path, monkeypatch):
    with SQLiteRepository(tmp_path / "failure.db") as repo:
        session = Session(SimulationSource(), repo)
        session.start()
        session.step()

        def fail():
            raise OSError("simulated disk failure")

        monkeypatch.setattr(session.recorder, "stop", fail)
        with pytest.raises(OSError):
            session.stop()
        assert session.source.state == "DISCONNECTED" and not session.running


def test_live_source_age_is_checked_in_shared_pipeline(tmp_path):
    class DelayedSource(SimulationSource):
        def get_current_timestamp_ms(self):
            return 5000

    with SQLiteRepository(tmp_path / "age.db") as repo:
        session = Session(DelayedSource(), repo)
        session.start()
        result = session.step()
        assert "stale" in result.issues
        assert result.sample.readings["RPM"].quality == Quality.STALE
        session.stop()
