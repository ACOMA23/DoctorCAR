"""New native-Qt acceptance run, with a new database and independently checked SQL."""

import json
import os
import sqlite3
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from doctorcar.ui.main_window import MainWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/evidence/acceptance-audit"
    output.mkdir(parents=True, exist_ok=True)
    database = root / "data/acceptance-audit" / f"e2e-{time.time_ns()}.sqlite3"
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    def wait_until(condition, timeout=35):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        raise AssertionError("Independent native GUI run timed out")

    def close(window):
        window.close()
        wait_until(lambda: not window.worker.isRunning(), timeout=5)
        app.processEvents()

    window = MainWindow(database)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    started = time.monotonic()
    try:
        wait_until(lambda: window.backend_ready)
        assert window.worker.starts == 0  # no auto-connect
        window.scenario_combo.setCurrentIndex(window.scenario_combo.findData("thermal"))
        window.speed_combo.setCurrentIndex(window.speed_combo.findData(30))
        window.start_button.click()
        wait_until(
            lambda: window.latest is not None and window.latest.timestamp_ms >= 95000
        )
        window.navigation.setCurrentRow(0)
        app.processEvents()
        assert window.latest.source.value == "SIMULATION"
        window.grab().save(str(output / "e2e-dashboard.png"))
        wait_until(lambda: window.latest.timestamp_ms >= 124000)
        wait_until(lambda: window.events_table.rowCount() == 1)
        window.open_event(0, 0)
        wait_until(lambda: "حدود النتيجة" in window.report_text.toPlainText())
        report_before = window.report_text.toPlainText()
        event_id = window.events_table.item(0, 3).text()
        assert "حالة التسجيل: مكتمل" in report_before
        assert window.worker.starts == 1
        window.grab().save(str(output / "e2e-report-before-restart.png"))
    finally:
        close(window)

    with sqlite3.connect(database) as sql:
        row = sql.execute(
            "SELECT status,trigger_ms,metadata_json FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        samples = [
            json.loads(r[0])
            for r in sql.execute(
                "SELECT m.data_json FROM measurements m JOIN event_samples e "
                "ON m.session_id=e.session_id AND m.sequence_number=e.sequence_number "
                "WHERE e.event_id=? ORDER BY m.timestamp_ms",
                (event_id,),
            )
        ]
        assert row[0] == "COMPLETE"
        assert samples[0]["timestamp_ms"] == row[1] - 30000
        assert samples[-1]["timestamp_ms"] == row[1] + 30000
        assert len(samples) == 301
        assert all(s["source"] == "SIMULATION" and s["raw"] for s in samples)
        assert sql.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not sql.execute("PRAGMA foreign_key_check").fetchall()

    reopened = MainWindow(database)
    reopened.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    reopened.show()
    try:
        wait_until(
            lambda: reopened.backend_ready and reopened.events_table.rowCount() == 1
        )
        assert reopened.worker.starts == 0
        reopened.open_event(0, 0)
        wait_until(lambda: "حدود النتيجة" in reopened.report_text.toPlainText())
        assert reopened.report_text.toPlainText() == report_before
        reopened.grab().save(str(output / "e2e-report-after-restart.png"))
    finally:
        close(reopened)
    (output / "e2e-report.txt").write_text(report_before, encoding="utf-8")
    summary = {
        "result": "PASS",
        "scope": "new thermal simulation through native GUI, SQLite, reload, report",
        "database": str(database),
        "event_id": event_id,
        "trigger_ms": row[1],
        "first_ms": samples[0]["timestamp_ms"],
        "last_ms": samples[-1]["timestamp_ms"],
        "sample_count": len(samples),
        "report_restored_identically": True,
        "sqlite_integrity": "ok",
        "wall_seconds": round(time.monotonic() - started, 3),
        "physical_hardware_tested": False,
    }
    (output / "e2e.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
