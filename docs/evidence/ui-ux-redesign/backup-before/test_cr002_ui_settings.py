import os
import re
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.sources.device_simulator import historical_events
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow


def wait(app, condition):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("UI condition timed out")


def close(app, window):
    window.close()
    wait(app, lambda: not window.worker.isRunning())
    app.processEvents()


def test_at010_source_fields_and_arguments_and_running_lock(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "sources.db")
    window.show()
    try:
        wait(app, lambda: window.backend_ready)
        window.navigation.setCurrentRow(1)
        window.source_combo.setCurrentIndex(3)
        window.port_input.setText("FAKE")
        assert window.source_arguments() == {"source": "serial", "port": "FAKE"}
        for control in (
            window.mode_combo,
            window.seed_input,
            window.fault_list,
            window.scenario_combo,
            window.path_input,
            window.speed_combo,
        ):
            assert control.isHidden()
        assert not window.port_combo.isHidden()
        for index in (1, 2):
            window.source_combo.setCurrentIndex(index)
            window.path_input.setText("file.jsonl")
            assert set(window.source_arguments()) == {"source", "path"}
            assert window.port_combo.isHidden() and not window.path_input.isHidden()
        window.source_combo.setCurrentIndex(0)
        assert window.port_combo.isHidden() and window.path_input.isHidden()
        assert not window.mode_combo.isHidden()
        window.mode_combo.setCurrentIndex(2)
        args = window.source_arguments()
        assert args["mode"] == "RANDOM_FAULTS" and "port" not in args and "path" not in args
        window.start_button.click()
        wait(app, lambda: window.latest is not None)
        assert not window.source_combo.isEnabled() and not window.verify_button.isEnabled()
        assert window.stop_button.isEnabled()
        window.stop_button.click()
        wait(app, lambda: window.source_combo.isEnabled())
        received = window.last_received
        window.language_combo.setCurrentIndex(1)
        assert window.last_received == received
        assert "Initializing" not in window.status_label.text()
    finally:
        close(app, window)


def test_at012_at013_theme_language_persist_and_legacy_report_intact(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "settings.db"
    event = historical_events()[0]
    with SQLiteRepository(path) as repo:
        repo.save_event(event)
        original = repo.get_event(event.event_id).to_dict()
        arabic_report = build_diagnostic_report(repo.get_event(event.event_id))
    window = MainWindow(path)
    window.show()
    try:
        wait(app, lambda: window.backend_ready and window.events_table.rowCount() == 1)
        window.language_combo.setCurrentIndex(1)
        window.theme_combo.setCurrentIndex(1)
        assert "Ready" in window.status_label.text()
        assert window.layoutDirection() == Qt.LayoutDirection.LeftToRight
        assert "#16232e" in window.styleSheet()
        for index in range(6):
            window.navigation.setCurrentRow(index)
            app.processEvents()
            for control in window.findChildren(QLabel) + window.findChildren(QPushButton):
                if control.isVisible():
                    assert not re.search("[\u0600-\u06ff]", control.text()), control.text()
        window.open_event(0, 0)
        wait(app, lambda: "experimental event report" in window.report_text.toPlainText())
        assert event.event_id in window.report_text.toPlainText()
        assert "Arabic preserved" in window.report_text.toPlainText()
    finally:
        close(app, window)
    reopened = MainWindow(path)
    reopened.show()
    try:
        wait(app, lambda: reopened.backend_ready)
        assert reopened.language == "en" and reopened.theme == "dark"
        assert reopened.layoutDirection() == Qt.LayoutDirection.LeftToRight
        reopened.theme_combo.setCurrentIndex(0)
        reopened.language_combo.setCurrentIndex(0)
        assert reopened.layoutDirection() == Qt.LayoutDirection.RightToLeft
        assert "#f4f7f8" in reopened.styleSheet()
    finally:
        close(app, reopened)
    with SQLiteRepository(path) as repo:
        assert repo.get_event(event.event_id).to_dict() == original
        assert build_diagnostic_report(repo.get_event(event.event_id)) == arabic_report
