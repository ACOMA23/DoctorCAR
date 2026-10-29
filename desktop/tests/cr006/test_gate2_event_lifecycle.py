"""DC-FIX-001 Gate 2: DEF-005 boundary handling of the T+30 s recording window."""

import pytest

from doctorcar.core.models import Reading, Sample, Source, Trigger
from doctorcar.monitoring.event_recorder import EventRecorder
from doctorcar.storage.sqlite_repository import SQLiteRepository

STEP = 200


def sample(t, session="trip"):
    return Sample(session, Source.SIMULATION, t // STEP, t, {"RPM": Reading(1500, "rpm")})


def trigger(t, kind="MS_SIGNAL"):
    return Trigger(kind, "ملاحظة", "سبب تجريبي", "test-v1", t)


def run(repo, script, end=200_000, session="trip"):
    """script: {time_ms: [Trigger, ...]}; one sample every 200 ms."""
    recorder = EventRecorder(repo)
    for t in range(0, end + STEP, STEP):
        recorder.append_measurement(sample(t, session), tuple(script.get(t, ())))
    recorder.stop()
    return repo.list_events()


@pytest.mark.parametrize(
    ("second_ms", "expected"),
    [
        (119_800, 1),  # still inside the 90 s event's window: same fault continuing
        (120_000, 2),  # exactly T+30: the defect swallowed this one
        (120_200, 2),
        (125_000, 2),
    ],
)
def test_repeat_of_same_kind_around_the_window_boundary(tmp_path, second_ms, expected):
    with SQLiteRepository(tmp_path / "e.sqlite3") as repo:
        repo.save_session("trip", "SIMULATION")
        rows = run(repo, {90_000: [trigger(90_000)], second_ms: [trigger(second_ms)]})
        assert len(rows) == expected
        assert {r["status"] for r in rows} == {"COMPLETE"}


def test_boundary_event_has_its_own_window_and_the_first_keeps_inclusive_end(tmp_path):
    with SQLiteRepository(tmp_path / "e.sqlite3") as repo:
        repo.save_session("trip", "SIMULATION")
        rows = run(repo, {90_000: [trigger(90_000)], 120_000: [trigger(120_000)]})
        events = sorted(
            (repo.get_event(r["event_id"]) for r in rows), key=lambda e: e.trigger.timestamp_ms
        )
        first, second = events
        assert first.samples[-1].timestamp_ms == 120_000  # T+30 inclusive, as before
        assert second.trigger.timestamp_ms == 120_000
        assert second.samples[0].timestamp_ms == 90_000  # its own T-30 s
        assert second.samples[-1].timestamp_ms == 150_000
        assert first.event_id != second.event_id


def test_persistent_trigger_does_not_duplicate_within_window(tmp_path):
    with SQLiteRepository(tmp_path / "e.sqlite3") as repo:
        repo.save_session("trip", "SIMULATION")
        script = {t: [trigger(t)] for t in range(90_000, 119_800 + STEP, STEP)}
        assert len(run(repo, script)) == 1


def test_event_that_disappears_and_returns_after_the_window_is_new(tmp_path):
    with SQLiteRepository(tmp_path / "e.sqlite3") as repo:
        repo.save_session("trip", "SIMULATION")
        script = {90_000: [trigger(90_000)], 140_000: [trigger(140_000)]}
        assert len(run(repo, script)) == 2


def test_different_kinds_overlap_independently(tmp_path):
    with SQLiteRepository(tmp_path / "e.sqlite3") as repo:
        repo.save_session("trip", "SIMULATION")
        script = {
            90_000: [trigger(90_000), trigger(90_000, "MS_THERMAL")],
            100_000: [trigger(100_000, "MS_AIRFLOW")],
        }
        rows = run(repo, script)
        assert sorted(r["kind"] for r in rows) == ["MS_AIRFLOW", "MS_SIGNAL", "MS_THERMAL"]


def test_same_kind_in_different_sessions_is_never_merged(tmp_path):
    with SQLiteRepository(tmp_path / "e.sqlite3") as repo:
        repo.save_session("a", "SIMULATION")
        repo.save_session("b", "SIMULATION")
        run(repo, {90_000: [trigger(90_000)]}, session="a")
        run(repo, {90_000: [trigger(90_000)]}, session="b")
        assert len(repo.list_events()) == 2


def test_events_survive_reopening_the_database(tmp_path):
    path = tmp_path / "e.sqlite3"
    with SQLiteRepository(path) as repo:
        repo.save_session("trip", "SIMULATION")
        run(repo, {90_000: [trigger(90_000)], 120_000: [trigger(120_000)]})
    with SQLiteRepository(path) as reopened:
        events = [reopened.get_event(r["event_id"]) for r in reopened.list_events()]
        assert len(events) == 2 and all(e.status == "COMPLETE" for e in events)


# --- DEF-012: Session enforces the analysis age / causality / session limits itself ---------
def _analysis(session_id, end_ms, decision="NORMAL"):
    return {
        "session_id": session_id,
        "start_ms": end_ms - 5000,
        "end_ms": end_ms,
        "decision": decision,
        "score": 0.4,
        "threshold": 0.58,
        "model_version": "stub-1",
        "model_sha256": "x",
    }


@pytest.mark.parametrize(
    ("analysis_session", "end_ms", "state_ok"),
    [("fx", 65_000, False), ("fx", 69_000, False), ("other", 67_500, False), ("fx", 67_500, True)],
)
def test_session_refuses_stale_future_or_foreign_analysis(analysis_session, end_ms, state_ok):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cr005"))
    from cr005_helpers import FakeRepo, StubAnalyzer, fixture_event

    from doctorcar.core.session import Session

    event = fixture_event()  # detection at 67 600 ms
    repo = FakeRepo()
    Session(
        object(),
        repo,
        analyzer=StubAnalyzer(
            _analysis(event.session_id if analysis_session == "fx" else "other", end_ms)
        ),
    )._record_ai_status(event)  # type: ignore[arg-type]
    status = repo.statuses[event.event_id]
    assert (status["state"] == "ANALYZED_NORMAL") is state_ok
    assert bool(repo.links) is state_ok
