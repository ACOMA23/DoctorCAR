import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from doctorcar.core.session import Session
from doctorcar.monitoring.simulation_evaluation import compare_schedule
from doctorcar.sources.replay import ReplaySource
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow


def wait(app, condition, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("GUI timed out")


def test_ms12_ms13_gui_scenario_evidence_report_restart_and_source_isolation(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "ui.db"
    window = MainWindow(path)
    window.show()
    report = ""
    try:
        wait(app, lambda: window.backend_ready)
        window.family_combo.setCurrentIndex(1)
        window.mode_combo.setCurrentIndex(1)
        window.multisensor_list.item(1).setCheckState(Qt.CheckState.Checked)
        args = window.source_arguments()
        assert args["scenarios"][0]["scenario_id"] == "S02" and "faults" not in args
        assert args["scenarios"][0]["duration_ms"] == 35000
        window.speed_combo.setCurrentIndex(2)
        window.start_button.click()
        wait(app, lambda: window.latest is not None)
        assert not window.family_combo.isEnabled()
        wait(
            app,
            lambda: any(
                r["kind"] == "MS_AIR_FUEL" and r["status"] == "COMPLETE" for r in window.event_rows
            ),
        )
        row = next(i for i, r in enumerate(window.event_rows) if r["kind"] == "MS_AIR_FUEL")
        assert int(window.events_table.item(row, 6).text()) >= 3
        assert window.events_table.item(row, 5).text() != "—"
        assert window.events_table.item(row, 7).text() != "—"
        assert "S02" in window.simulation_summary.toPlainText()
        assert "DoctorCAR: MS_AIR_FUEL" in window.simulation_summary.toPlainText()
        window.stop_button.click()
        wait(app, lambda: window.start_button.isEnabled())
        window.open_event(row, 0)
        wait(app, lambda: "A. الأعراض" in window.report_text.toPlainText())
        report = window.report_text.toPlainText()
        window.source_combo.setCurrentIndex(3)
        assert window.family_combo.isHidden() and window.multisensor_list.isHidden()
        assert set(window.source_arguments()) == {"source", "port"}
    finally:
        window.close()
        wait(app, lambda: not window.worker.isRunning(), 5)
        app.processEvents()
    reopened = MainWindow(path)
    reopened.show()
    try:
        wait(app, lambda: reopened.backend_ready and bool(reopened.event_rows))
        row = next(i for i, r in enumerate(reopened.event_rows) if r["kind"] == "MS_AIR_FUEL")
        reopened.open_event(row, 0)
        wait(app, lambda: reopened.report_text.toPlainText() == report)
        assert reopened.language == "ar" and reopened.theme == "light"
    finally:
        reopened.close()
        wait(app, lambda: not reopened.worker.isRunning(), 5)
        app.processEvents()


def test_ms13_multisensor_replay_keeps_calibration_and_value_based_rules(tmp_path):
    source = SimulationSource(
        scenario_family="multisensor",
        mode="FAULT_INJECTION",
        scenarios=(ScenarioInstance("S04"),),
        step_ms=1000,
    )
    with SQLiteRepository(tmp_path / "replay.db") as repo:
        session = Session(source, repo)
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        path = tmp_path / "replay.jsonl"
        repo.export_session(session.last_sample.session_id, path)
        replay = Session(ReplaySource(path), repo)
        replay.start()
        while not replay.source.exhausted:
            replay.step()
        replay.stop()
        events = [r for r in repo.list_events() if r["kind"] == "MS_AIRFLOW"]
        assert len(events) == 2 and {r["origin"] for r in events} == {"LIVE", "REPLAY"}
        assert len({r["trigger_ms"] for r in events}) == 1


def test_evaluation_does_not_count_arbitrary_event_as_correct_diagnosis():
    source = SimulationSource(
        scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02"),)
    )
    metadata = source.get_simulation_metadata()
    rows = [
        {"event_id": "no-evidence", "kind": "MS_AIR_FUEL", "trigger_ms": 67000},
        {"event_id": "wrong-pattern", "kind": "MS_AIRFLOW", "trigger_ms": 68000},
        {"event_id": "false-normal", "kind": "MS_THERMAL", "trigger_ms": 10000},
    ]
    result = compare_schedule(metadata, rows, 155000)
    assert result["faults"][0]["status"] == "NOT_DETECTED"
    assert result["faults"][0]["unverified_event_ids"] == ["no-evidence"]
    assert result["false_positive_events_on_known_normal"] == ["false-normal"]
    assert len(result["unmatched_events"]) == 3
    assert result["causal_diagnostic_accuracy"] == "NOT_MEASURED"
