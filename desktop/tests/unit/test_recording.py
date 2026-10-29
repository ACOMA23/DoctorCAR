import sqlite3
from dataclasses import replace

import pytest

from doctorcar.core.models import Event, Reading, Sample, Source, Trigger
from doctorcar.monitoring.event_detector import EventDetector
from doctorcar.monitoring.event_recorder import EventRecorder
from doctorcar.monitoring.ring_buffer import TimeRingBuffer
from doctorcar.storage.sqlite_repository import SQLiteRepository


def sample(t, seq=None, session="trip"):
    return Sample(
        session,
        Source.SIMULATION,
        t if seq is None else seq,
        t,
        {"RPM": Reading(1500, "rpm"), "COOLANT_TEMP": Reading(115, "°C")},
    )


def trigger(t, kind="TEST"):
    return Trigger(kind, "ملاحظة", "سبب تجريبي", "test-v1", t)


def test_time_buffer_irregular_samples():
    buffer = TimeRingBuffer()
    for t in (0, 5, 9000, 30000, 30001, 59000):
        buffer.append_measurement(sample(t))
    assert [s.timestamp_ms for s in buffer.get_pre_event_window(59000)] == [30000, 30001, 59000]
    with pytest.raises(ValueError):
        buffer.append_measurement(sample(59001, session="other"))


def test_pre_post_overlap_dedup_and_reopen(tmp_path):
    path = tmp_path / "events.sqlite3"
    with SQLiteRepository(path) as repo:
        repo.save_session("trip", "SIMULATION")
        recorder = EventRecorder(repo)
        for t in range(0, 81000, 1000):
            triggers = (trigger(t),) if t in (40000, 41000) else ()
            if t == 45000:
                triggers = (trigger(t, "OTHER"),)
            recorder.append_measurement(sample(t), triggers)
        rows = repo.list_events()
        assert len(rows) == 2
        assert {r["status"] for r in rows} == {"COMPLETE"}
        first = repo.get_event(next(r["event_id"] for r in rows if r["kind"] == "TEST"))
        assert first.samples[0].timestamp_ms == 10000
        assert first.samples[-1].timestamp_ms == 70000
        assert len(first.samples) == 61
        repo.save_event(first)
        assert len(repo.list_events()) == 2
        assert repo.connection.execute("SELECT count(*) FROM measurements").fetchone()[0] == 66
    with SQLiteRepository(path) as reopened:
        restored = reopened.get_event(first.event_id)
        assert restored.to_dict() == first.to_dict()


def test_partial_on_stop_and_short_pre_window(tmp_path):
    with SQLiteRepository(tmp_path / "partial.db") as repo:
        recorder = EventRecorder(repo)
        recorder.append_measurement(sample(0), (trigger(0),))
        recorder.append_measurement(sample(500), ())
        recorder.stop()
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert event.status == "PARTIAL"
        assert len(event.limitations) == 2


def test_abrupt_interruption_recovers_checkpoint(tmp_path):
    path = tmp_path / "crash.db"
    repo = SQLiteRepository(path)
    recorder = EventRecorder(repo)
    recorder.append_measurement(sample(40000), (trigger(40000),))
    recorder.append_measurement(sample(41000), ())
    repo.close()  # intentionally no recorder.stop(), analogous to last committed checkpoint
    with SQLiteRepository(path) as recovered:
        event = recovered.get_event(recovered.list_events()[0]["event_id"])
        assert event.status == "PARTIAL" and event.end_ms == 41000
        assert len(event.samples) == 2


def test_atomic_conflict_and_finalized_immutability(tmp_path):
    with SQLiteRepository(tmp_path / "atomic.db") as repo:
        event = Event("event", "trip", trigger(0), [sample(0)], "COMPLETE", 0)
        repo.save_event(event)
        with pytest.raises(ValueError):
            repo.save_event(replace(event, status="PARTIAL"))
        with pytest.raises(ValueError):
            repo.save_event(
                replace(event, event_id="bad", samples=[replace(sample(0), phase="conflict")])
            )
        assert len(repo.list_events()) == 1


def test_future_schema_rejected(tmp_path):
    path = tmp_path / "future.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version=99")
    con.close()
    with pytest.raises(ValueError):
        SQLiteRepository(path)


def test_thermal_rule_requires_duration_and_context():
    detector = EventDetector()
    assert not detector.evaluate_trigger(sample(0), ())
    assert not detector.evaluate_trigger(sample(2000), ())
    event = detector.evaluate_trigger(sample(3000), ())
    assert event[0].kind == "THERMAL_DEMO"
    assert not detector.evaluate_trigger(sample(4000), ())
    bad = replace(sample(5000), readings={"COOLANT_TEMP": Reading(None, "°C")})
    assert not detector.evaluate_trigger(bad, ())


def test_no_dtc_required_and_constant_normal_value_is_not_fault():
    detector = EventDetector()
    for t in range(0, 10000, 1000):
        s = replace(
            sample(t), readings={"COOLANT_TEMP": Reading(90, "°C"), "RPM": Reading(1500, "rpm")}
        )
        assert not detector.evaluate_trigger(s, ())
    assert EventDetector().evaluate_trigger(sample(0), ("missing:MAF",))[0].kind == "DATA_QUALITY"
