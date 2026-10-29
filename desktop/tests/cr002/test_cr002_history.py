from doctorcar.core.session import Session
from doctorcar.sources.device_simulator import SimulatedDeviceSource, historical_events
from doctorcar.storage.sqlite_repository import SQLiteRepository


def test_history_complete_stable_and_same_import_pipeline(tmp_path):
    expected = historical_events(42)
    assert len(expected) == 2
    assert [e.to_dict() for e in expected] == [e.to_dict() for e in historical_events(42)]
    with SQLiteRepository(tmp_path / "history.sqlite3") as repo:
        interrupted = Session(SimulatedDeviceSource(), repo)
        interrupted.start()
        for _ in range(5):
            interrupted.step()
        interrupted.stop()
        assert repo.list_events() == []  # no partial upload committed
        for _ in range(2):
            session = Session(SimulatedDeviceSource(), repo)
            session.start()
            while not session.source.exhausted:
                session.step()
            session.stop()
        rows = repo.list_events()
        assert len(rows) == 2
        for row in rows:
            event = repo.get_event(row["event_id"])
            assert event is not None
            assert event.origin == "HISTORICAL"
            assert event.status == "COMPLETE"
            assert event.samples[0].timestamp_ms == event.trigger.timestamp_ms - 30_000
            assert event.samples[-1].timestamp_ms == event.trigger.timestamp_ms + 30_000
            assert len({s.session_id for s in event.samples}) == 1
