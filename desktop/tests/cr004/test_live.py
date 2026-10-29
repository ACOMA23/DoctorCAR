from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.model import MODEL_V1, AnomalyModel
from doctorcar.core.session import Session
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def test_live_ml_preserves_every_sample_and_records_versioned_results(tmp_path):
    path = tmp_path / "live.db"
    source = SimulationSource(
        scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02"),)
    )
    with SQLiteRepository(path) as repo:
        session = Session(source, repo, analyzer=AnomalyAnalyzer(AnomalyModel(MODEL_V1)))
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        assert session.accepted == 776 and session.rejected == 0
        assert repo.connection.execute("select count(*) from measurements").fetchone()[0] == 776
        rows = repo.list_events()
        assert rows
        analyzed = [repo.get_event_analysis(r["event_id"]) for r in rows]
        assert any(a and a["model_version"] == "iforest-cr004-v1" for a in analyzed)
        complete = [
            repo.get_event(r["event_id"])
            for r in rows
            if r["status"] == "COMPLETE" and r["trigger_ms"] >= 30000
        ]
        assert complete
        for e in complete:
            assert len(e.samples) == 301
            assert e.samples[0].timestamp_ms == e.trigger.timestamp_ms - 30000
            assert e.samples[-1].timestamp_ms == e.trigger.timestamp_ms + 30000
    with SQLiteRepository(path) as repo:
        assert repo.list_events() == rows
        assert [repo.get_event_analysis(r["event_id"]) for r in rows] == analyzed


def test_ml_failure_leaves_rules_and_recording_running(tmp_path):
    class Broken:
        def push(self, sample):
            raise RuntimeError("intentional inference failure")

    source = SimulationSource("thermal")
    with SQLiteRepository(tmp_path / "failure.db") as repo:
        session = Session(source, repo, analyzer=Broken())
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        assert session.accepted == 776
        assert session.ai_status["decision"] == "UNAVAILABLE"
        assert any(
            r["kind"] == "THERMAL_DEMO" and r["status"] == "COMPLETE" for r in repo.list_events()
        )
