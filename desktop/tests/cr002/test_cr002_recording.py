from doctorcar.core.session import Session
from doctorcar.monitoring.simulation_evaluation import compare_schedule
from doctorcar.sources.faults import FaultInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def run(repo, faults):
    source = SimulationSource(
        mode="FAULT_INJECTION", faults=faults, step_ms=1000, duration_ms=110000
    )
    session = Session(source, repo)
    session.start()
    while not source.exhausted:
        session.step()
    session.stop()
    return session


def test_at002_short_fault_stops_at65_but_recording_continues_until93_and_reload(tmp_path):
    path = tmp_path / "short.db"
    with SQLiteRepository(path) as repo:
        run(repo, (FaultInstance("thermal_sudden", 60000, 5000),))
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert event.trigger.timestamp_ms == 63000
        assert event.status == "COMPLETE"
        assert [event.samples[0].timestamp_ms, event.samples[-1].timestamp_ms] == [33000, 93000]
        assert event.samples[32].readings["COOLANT_TEMP"].value < 108
        data = event.to_dict()
        metadata = repo.get_simulation_run(event.session_id)
        assert metadata["seed"] == 42 and metadata["fault_schedule"][0]["start_ms"] == 60000
        evaluation = compare_schedule(metadata, repo.list_events(), 110000)
        assert evaluation["faults"][0]["status"] == "DETECTED"
    with SQLiteRepository(path) as repo:
        assert repo.get_event(event.event_id).to_dict() == data


def test_at005_overlap_display_only_fault_has_no_fake_detection(tmp_path):
    with SQLiteRepository(tmp_path / "multi.db") as repo:
        run(
            repo,
            (
                FaultInstance("thermal_sudden"),
                FaultInstance("low_voltage"),
                FaultInstance("maf_bias"),
            ),
        )
        events = repo.list_events()
        assert len(events) == 1
        metadata = repo.get_simulation_run(events[0]["session_id"])
        evaluation = compare_schedule(metadata, events, 110000)
        assert [f["status"] for f in evaluation["faults"]] == [
            "DETECTED",
            "NOT_DETECTED",
            "NOT_DETECTED",
        ]
        assert evaluation["unmatched_events"] == []


def test_at014_export_and_complete_replay_create_isolated_event(tmp_path):
    from doctorcar.diagnostics.reports import build_diagnostic_report
    from doctorcar.sources.replay import ReplaySource

    path = tmp_path / "full-replay.jsonl"
    with SQLiteRepository(tmp_path / "full-replay.db") as repo:
        original = run(repo, (FaultInstance("thermal_sudden"),))
        repo.export_session(original.last_sample.session_id, path)
        replay = Session(ReplaySource(path), repo)
        assert replay.source.verify()["ok"]
        replay.start()
        while not replay.source.exhausted:
            replay.step()
        replay.stop()
        events = repo.list_events()
        assert len(events) == 2
        event = repo.get_event(next(r["event_id"] for r in events if r["origin"] == "REPLAY"))
        assert event.session_id != original.last_sample.session_id
        assert event.trigger.timestamp_ms == 63000 and event.status == "COMPLETE"
        assert (event.samples[0].timestamp_ms, event.samples[-1].timestamp_ms) == (33000, 93000)
        assert "REPLAY" in build_diagnostic_report(event)


def test_v1_database_upgrade_preserves_existing_event_and_report(tmp_path):
    import json
    import sqlite3

    from doctorcar.diagnostics.reports import build_diagnostic_report

    path = tmp_path / "v1.db"
    with SQLiteRepository(path) as repo:
        run(repo, (FaultInstance("thermal_sudden"),))
        event = repo.get_event(repo.list_events()[0]["event_id"])
        original, report = event.to_dict(), build_diagnostic_report(event)
    with sqlite3.connect(path) as sql:
        sql.execute("DROP TABLE simulation_runs")
        metadata = json.loads(sql.execute("SELECT metadata_json FROM events").fetchone()[0])
        metadata.pop("origin")
        sql.execute("UPDATE events SET metadata_json=?", (json.dumps(metadata),))
        sql.execute("PRAGMA user_version=1")
    with SQLiteRepository(path) as repo:
        assert repo.connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert repo.get_event(event.event_id).to_dict() == original
        assert build_diagnostic_report(repo.get_event(event.event_id)) == report
        assert repo.list_events()[0]["origin"] == "LIVE"
