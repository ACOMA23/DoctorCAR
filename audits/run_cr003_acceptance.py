"""Software-only measurement audit and native GUI evidence for DC-CR-003."""

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from doctorcar.core.session import Session
from doctorcar.diagnostics.evidence import build_evidence
from doctorcar.diagnostics.hypotheses import evaluate_hypotheses
from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.monitoring.simulation_evaluation import compare_schedule
from doctorcar.sources.scenarios import SCENARIOS_MS, ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/evidence/dc-cr-003"
    output.mkdir(parents=True, exist_ok=True)
    directory = root / f"data/cr003-audit-{time.time_ns()}"
    directory.mkdir(parents=True)
    cases = []
    database = directory / "cohort.sqlite3"
    with SQLiteRepository(database) as repo:
        for group, start, duration, severity, seed in (
            ("development", 60000, 35000, 1.0, 42),
            ("parameter_variation", 55000, 9000, 0.65, 73),
            ("parameter_variation", 80000, 20000, 0.9, 97),
        ):
            for sid in SCENARIOS_MS:
                source = SimulationSource(
                    scenario_family="multisensor",
                    mode="FAULT_INJECTION",
                    scenarios=(
                        ScenarioInstance(
                            sid,
                            start,
                            duration,
                            severity,
                            "flatline"
                            if sid == "S07" and group == "parameter_variation"
                            else "default",
                        ),
                    ),
                    step_ms=1000,
                    seed=seed,
                )
                session = Session(source, repo)
                session.start()
                while not source.exhausted:
                    session.step()
                session.stop()
                rows = [
                    r
                    for r in repo.list_events()
                    if r["session_id"] == session.last_sample.session_id
                ]
                details = {r["event_id"]: repo.get_event(r["event_id"]) for r in rows}
                comparison = compare_schedule(
                    source.get_simulation_metadata(), rows, 155000, details
                )
                cases.append(
                    {
                        "group": group,
                        "scenario": sid,
                        "configuration": asdict(source.scenarios[0]),
                        "seed": seed,
                        "comparison": comparison,
                        "all_detected_patterns": [
                            r["kind"] for r in rows if r["kind"].startswith("MS_")
                        ],
                    }
                )
        for seed in (42, 73, 97):
            source = SimulationSource(
                scenario_family="multisensor", mode="NORMAL", step_ms=1000, seed=seed
            )
            session = Session(source, repo)
            session.start()
            while not source.exhausted:
                session.step()
            session.stop()
            rows = [
                r
                for r in repo.list_events()
                if r["session_id"] == session.last_sample.session_id
            ]
            assert rows == [], rows
            cases.append({"group": "normal", "seed": seed, "false_alarms": len(rows)})
        assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    disturbed = [c for c in cases if c["group"] != "normal"]
    detected = [
        c
        for c in disturbed
        if c["comparison"]["faults"][0]["status"] == "PATTERN_DETECTED"
    ]
    missed = [
        {
            "group": c["group"],
            "scenario": c["scenario"],
            "configuration": c["configuration"],
            "detected_patterns": c["all_detected_patterns"],
        }
        for c in disturbed
        if c not in detected
    ]
    evaluation = {
        "scope": "Toy-model pattern agreement only; parameter variations are NOT independent vehicle validation",
        "causal_diagnostic_accuracy": "NOT_MEASURED",
        "scheduled_cases": len(disturbed),
        "expected_pattern_detected": len(detected),
        "missed_or_unmanifested": missed,
        "normal_runs": 3,
        "normal_run_false_alarms": 0,
        "unmatched_events": sum(
            len(c["comparison"]["unmatched_events"]) for c in disturbed
        ),
        "known_normal_period_false_positive_events": sum(
            len(c["comparison"]["false_positive_events_on_known_normal"])
            for c in disturbed
        ),
        "cases": cases,
        "database": str(database),
    }
    (output / "simulation-evaluation.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Cohort: {len(detected)}/{len(disturbed)} scheduled patterns detected; {len(missed)} missed/unmanifested; normal false alarms=0",
        flush=True,
    )

    # Actual Qt widgets and worker, no physical port, new database and settings file.
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    gui_db = directory / "gui.sqlite3"
    errors = []

    def wait(condition, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        raise AssertionError(f"Qt acceptance timed out: {errors}")

    def open_window():
        window = MainWindow(gui_db)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1560, 1000)
        window.worker.error.connect(errors.append)
        window.show()
        wait(lambda: window.backend_ready)
        return window

    def close(window):
        window.close()
        wait(lambda: not window.worker.isRunning(), 5)
        app.processEvents()

    window = open_window()
    try:
        window.navigation.setCurrentRow(1)
        window.family_combo.setCurrentIndex(1)
        window.mode_combo.setCurrentIndex(1)
        window.multisensor_list.item(1).setCheckState(Qt.CheckState.Checked)
        window.speed_combo.setCurrentIndex(2)
        app.processEvents()
        window.grab().save(str(output / "source-multisensor-ar.png"))
        window.start_button.click()
        wait(lambda: window.latest is not None)
        wait(lambda: window.start_button.isEnabled())
        row = next(
            i for i, r in enumerate(window.event_rows) if r["kind"] == "MS_AIR_FUEL"
        )
        event_id = window.event_rows[row]["event_id"]
        window.navigation.setCurrentRow(3)
        app.processEvents()
        window.grab().save(str(output / "events-evidence-ar.png"))
        window.navigation.setCurrentRow(0)
        app.processEvents()
        window.grab().save(str(output / "injected-versus-detected-ar.png"))
        window.open_event(row, 0)
        wait(lambda: "A. الأعراض" in window.report_text.toPlainText())
        report = window.report_text.toPlainText()
        (output / "example-report-ar.txt").write_text(report, encoding="utf-8")
        window.grab().save(str(output / "report-ms-ar.png"))
        window.language_combo.setCurrentIndex(1)
        window.theme_combo.setCurrentIndex(1)
        window.open_event(row, 0)
        wait(lambda: "A. Observed Symptoms" in window.report_text.toPlainText())
        report_en = window.report_text.toPlainText()
        window.grab().save(str(output / "report-ms-en-dark.png"))
    finally:
        close(window)
    reopened = open_window()
    try:
        assert reopened.language == "en" and reopened.theme == "dark"
        row = next(
            i for i, r in enumerate(reopened.event_rows) if r["event_id"] == event_id
        )
        reopened.open_event(row, 0)
        wait(lambda: reopened.report_text.toPlainText() == report_en)
        reopened.grab().save(str(output / "report-after-restart.png"))
    finally:
        close(reopened)
    assert not errors, errors
    with SQLiteRepository(gui_db) as repo:
        event = repo.get_event(event_id)
        evidence = build_evidence(event)
        assert event.status == "COMPLETE"
        assert event.samples[0].timestamp_ms == event.trigger.timestamp_ms - 30000
        assert event.end_ms == event.trigger.timestamp_ms + 30000
        assert build_diagnostic_report(event) == report
        assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not repo.connection.execute("PRAGMA foreign_key_check").fetchall()
        example = {
            "event_id": event_id,
            "kind": event.trigger.kind,
            "trigger_ms": event.trigger.timestamp_ms,
            "first_ms": event.samples[0].timestamp_ms,
            "last_ms": event.end_ms,
            "samples": len(event.samples),
            "measurements": {k: asdict(v) for k, v in evidence.measurements.items()},
            "findings": [asdict(f) for f in evidence.findings],
            "hypotheses": [asdict(h) for h in evaluate_hypotheses(event, evidence)],
        }
    (output / "example-event.json").write_text(
        json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = {
        "result": "PASS",
        "scope": "native Qt -> controlled multisensor -> event -> SQLite -> A-K report -> restart",
        "database": str(gui_db),
        "event_id": event_id,
        "trigger_ms": event.trigger.timestamp_ms,
        "first_ms": event.samples[0].timestamp_ms,
        "last_ms": event.end_ms,
        "samples": len(event.samples),
        "report_restored_identically": True,
        "sqlite_integrity": "ok",
        "firmware_modified": False,
        "physical_hardware_tested": False,
    }
    (output / "e2e.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
