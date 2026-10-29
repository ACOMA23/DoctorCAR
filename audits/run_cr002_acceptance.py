"""Reproducible native Qt acceptance evidence for DC-CR-002; no physical ports."""

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from doctorcar.monitoring.simulation_evaluation import compare_schedule
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/evidence/dc-cr-002"
    output.mkdir(parents=True, exist_ok=True)
    database = root / f"data/cr002-e2e-{time.time_ns()}/doctorcar.sqlite3"
    database.parent.mkdir(parents=True)
    replay_path = database.parent / "controlled.jsonl"
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors = []
    summary = {"database": str(database), "hardware_tested": False, "phases": []}

    def wait(condition, timeout=40):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        raise AssertionError(f"Acceptance condition timed out; errors={errors}")

    def window_open():
        window = MainWindow(database)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.resize(1360, 1000)
        window.worker.error.connect(errors.append)
        window.show()
        wait(lambda: window.backend_ready)
        return window

    def close(window):
        window.close()
        wait(lambda: not window.worker.isRunning(), 5)
        app.processEvents()

    def run_until_finished(window):
        previous = window.latest.session_id if window.latest else None
        window.start_button.click()
        wait(lambda: window.latest is not None and window.latest.session_id != previous)
        wait(lambda: window.start_button.isEnabled())
        return window.latest.session_id

    def record(name, **evidence):
        summary["phases"].append({"name": name, **evidence})
        print(name + ": PASS", flush=True)

    window = window_open()
    try:
        # Controlled short, compatible faults, through the actual GUI worker.
        window.navigation.setCurrentRow(1)
        window.mode_combo.setCurrentIndex(1)
        for i in range(window.fault_list.count()):
            if window.fault_list.item(i).data(Qt.ItemDataRole.UserRole) in (
                "thermal_sudden",
                "low_voltage",
                "maf_bias",
            ):
                window.fault_list.item(i).setCheckState(Qt.CheckState.Checked)
        window.speed_combo.setCurrentIndex(2)
        session_id = run_until_finished(window)
        wait(lambda: window.events_table.rowCount() == 1)
        event_id = window.events_table.item(0, 3).text()
        window.open_event(0, 0)
        wait(lambda: "حالة التسجيل: مكتمل" in window.report_text.toPlainText())
        report_ar = window.report_text.toPlainText()
        window.grab().save(str(output / "controlled-report-ar-light.png"))
        window.worker.submit("export", session_id=session_id, path=str(replay_path))
        wait(lambda: replay_path.exists())
        with SQLiteRepository(database) as repo:
            event = repo.get_event(event_id)
            assert event.trigger.timestamp_ms == 63000
            assert event.samples[0].timestamp_ms == 33000
            assert event.samples[-1].timestamp_ms == 93000
            assert len(event.samples) == 301 and event.status == "COMPLETE"
            evaluation = compare_schedule(
                repo.get_simulation_run(session_id), repo.list_events(), 155000
            )
            assert sorted(f["status"] for f in evaluation["faults"]) == [
                "DETECTED",
                "NOT_DETECTED",
                "NOT_DETECTED",
            ]
        (output / "controlled-report-ar.txt").write_text(report_ar, encoding="utf-8")
        record(
            "controlled short fault / save / report / export",
            event_id=event_id,
            trigger_ms=63000,
            first_ms=33000,
            last_ms=93000,
            sample_count=301,
            evaluation=evaluation,
        )

        # Source-aware replay and existing report pipeline.
        window.source_combo.setCurrentIndex(1)
        window.path_input.setText(str(replay_path))
        window.verify_button.click()
        wait(lambda: window.verify_button.isEnabled())
        previous = window.latest.session_id
        window.start_button.click()
        wait(
            lambda: (
                window.latest.session_id != previous
                and window.latest.timestamp_ms >= 1000
            )
        )
        assert window.latest.source.value == "REPLAY"
        window.stop_button.click()
        wait(lambda: window.start_button.isEnabled())
        record("exported Replay validation and playback", replay=str(replay_path))

        # Historical uploads followed by a new live session; repeat the whole connection.
        window.source_combo.setCurrentIndex(4)
        for attempt in range(2):
            previous = window.latest.session_id
            window.start_button.click()
            wait(
                lambda previous=previous: (
                    window.latest.session_id != previous
                    and window.latest.timestamp_ms >= 6000
                )
            )
            window.stop_button.click()
            wait(lambda: window.start_button.isEnabled())
            wait(lambda: window.events_table.rowCount() == 3)
        history = [r for r in window.event_rows if r["origin"] == "HISTORICAL"]
        assert len(history) == 2
        window.navigation.setCurrentRow(3)
        app.processEvents()
        window.grab().save(str(output / "history-ar-light.png"))
        record("historical import and reconnect idempotency", events=history)

        # Same seed at two actual GUI display speeds, settings and every reading match.
        random_runs = []
        window.source_combo.setCurrentIndex(0)
        window.mode_combo.setCurrentIndex(2)
        window.seed_input.setValue(73)
        for speed in (30, 10):
            window.speed_combo.setCurrentIndex(window.speed_combo.findData(speed))
            sid = run_until_finished(window)
            with SQLiteRepository(database) as repo:
                metadata = repo.get_simulation_run(sid)
                samples = [
                    json.loads(r[0])
                    for r in repo.connection.execute(
                        "SELECT data_json FROM measurements WHERE session_id=? "
                        "ORDER BY sequence_number",
                        (sid,),
                    )
                ]
                random_runs.append((metadata, [s["readings"] for s in samples]))
                evaluation = compare_schedule(
                    metadata,
                    [r for r in repo.list_events() if r["session_id"] == sid],
                    155000,
                )
            (output / f"random-{speed}x.json").write_text(
                json.dumps(
                    {
                        "metadata": metadata,
                        "evaluation": evaluation,
                        "sample_count": len(samples),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        assert random_runs[0] == random_runs[1]
        assert [c["start_ms"] for c in random_runs[0][0]["cycles"]][:4] == [
            30000,
            60000,
            90000,
            120000,
        ]
        record(
            "random seed and all readings independent of actual 10x/30x GUI speed",
            seed=73,
            sample_count=len(random_runs[0][1]),
        )

        # Legacy thermal remains available and uses the original path.
        window.scenario_combo.setCurrentIndex(1)
        window.speed_combo.setCurrentIndex(2)
        legacy_session = run_until_finished(window)
        with SQLiteRepository(database) as repo:
            legacy = [
                r for r in repo.list_events() if r["session_id"] == legacy_session
            ]
            assert len(legacy) == 1 and legacy[0]["trigger_ms"] == 89000
        record("legacy thermal regression", trigger_ms=89000)

        window.language_combo.setCurrentIndex(1)
        window.theme_combo.setCurrentIndex(1)
        window.navigation.setCurrentRow(5)
        app.processEvents()
        window.grab().save(str(output / "settings-en-dark.png"))
        row = next(
            i for i, r in enumerate(window.event_rows) if r["event_id"] == event_id
        )
        window.open_event(row, 0)
        wait(lambda: "experimental event report" in window.report_text.toPlainText())
        report_en = window.report_text.toPlainText()
        window.grab().save(str(output / "controlled-report-en-dark.png"))
    finally:
        close(window)

    reopened = window_open()
    try:
        assert reopened.language == "en" and reopened.theme == "dark"
        assert reopened.layoutDirection() == Qt.LayoutDirection.LeftToRight
        row = next(
            i for i, r in enumerate(reopened.event_rows) if r["event_id"] == event_id
        )
        reopened.open_event(row, 0)
        wait(lambda: reopened.report_text.toPlainText() == report_en)
        reopened.grab().save(str(output / "report-after-restart-en-dark.png"))
        record("restart restores EN, Dark, LTR and identical report", event_id=event_id)
    finally:
        close(reopened)
    with SQLiteRepository(database) as repo:
        assert repo.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not repo.connection.execute("PRAGMA foreign_key_check").fetchall()
        assert len([r for r in repo.list_events() if r["origin"] == "HISTORICAL"]) == 2
    assert not errors, errors
    summary.update(result="PASS", errors=errors, sqlite_integrity="ok")
    (output / "e2e.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"result": "PASS", "database": str(database)}, indent=2))


if __name__ == "__main__":
    main()
