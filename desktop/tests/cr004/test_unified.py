import json
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.model import MODEL_DIR, MODEL_V1, AnomalyModel
from doctorcar.core.session import Session
from doctorcar.diagnostics.human_report import build_report_model, render_simple, render_technical
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow


def wait(app, predicate, seconds=15):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


def test_unified_report_saved_ar_en_xai_no_future_or_retraining(tmp_path):
    path = tmp_path / "report.db"
    source = SimulationSource(
        scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02"),)
    )
    with SQLiteRepository(path) as repo:
        session = Session(source, repo, analyzer=AnomalyAnalyzer(AnomalyModel(MODEL_V1)))
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        rows = repo.list_events()
        selected = next(
            r
            for r in rows
            if r["status"] == "COMPLETE"
            and (a := repo.get_event_analysis(r["event_id"]))
            and a.get("xai", {}).get("status") == "AVAILABLE"
        )
        event = repo.get_event(selected["event_id"])
        analysis = repo.get_event_analysis(event.event_id)
        report = build_report_model(event, analysis)
        assert analysis["end_ms"] == analysis["xai"]["end_ms"]
        assert "العوامل" in render_simple(report)
        assert "COOLANT_TEMP.mean" not in render_simple(report)
        assert "feature_units" in render_technical(report)
        assert "Model" not in render_simple(report)
        stored = json.loads(
            repo.connection.execute(
                "select data_json from diagnostic_reports where event_id=?", (event.event_id,)
            ).fetchone()[0]
        )
        assert stored["analysis"] == analysis
        english = render_simple(report, "en")
        assert "model effects, not mechanical causes" in english
        if event.trigger.kind == "ML_ANOMALY":
            supported = build_report_model(event, analysis, repo.get_detections(event.event_id))
            later = [d for d in supported.detection_sources if d["kind"].startswith("MS_")]
            if later:
                assert supported.hypothesis_evidence_ms == min(d["timestamp_ms"] for d in later)
                assert supported.analysis["end_ms"] == analysis["end_ms"]
    app = QApplication.instance() or QApplication([])
    mtime = (MODEL_DIR / "model.joblib").stat().st_mtime_ns
    window = MainWindow(path)
    window.show()
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    try:
        wait(app, lambda: window.backend_ready and window.events_table.rowCount() > 0)
        window.worker.submit("report", event_id=event.event_id, language="ar")
        wait(app, lambda: "العوامل" in window.simple_report_text.toPlainText())
        assert not window.report_text.isVisible()
        window.technical_button.setChecked(True)
        app.processEvents()
        assert window.report_text.isVisible() and window.time_plot.isVisible()
        assert window.time_plot.selector.count() == 11
        window.worker.submit("report", event_id=event.event_id, language="en")
        wait(app, lambda: "What did AI observe?" in window.simple_report_text.toPlainText())
        assert len(ticks) > 0
    finally:
        timer.stop()
        window.worker.shutdown()
        assert window.worker.wait(5000)
        window.close()
    assert (MODEL_DIR / "model.joblib").stat().st_mtime_ns == mtime
