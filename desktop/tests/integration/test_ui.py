import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from doctorcar.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("GUI condition timed out")


def test_rtl_navigation_single_session_and_async_close(app, tmp_path):
    window = MainWindow(tmp_path / "ui.db")
    window.show()
    try:
        wait_for(app, lambda: window.backend_ready)
        assert window.layoutDirection() == Qt.LayoutDirection.RightToLeft
        window.scenario_combo.setCurrentIndex(1)
        window.speed_combo.setCurrentIndex(2)
        window.start_button.click()
        wait_for(app, lambda: window.latest is not None)
        first_sequence = window.latest.sequence_number
        # Repeated start must neither stop nor duplicate the active session.
        window.start_button.click()
        for i in range(30):
            window.navigation.setCurrentRow(i % 6)
            app.processEvents()
        wait_for(app, lambda: window.latest.sequence_number > first_sequence)
        assert window.worker.starts == 1
        assert window.sensor_table.rowCount() == 12
        assert "SIMULATION" in window.context.text()
    finally:
        window.close()
        wait_for(app, lambda: not window.worker.isRunning())
        app.processEvents()


def test_backend_storage_error_is_visible_and_gui_survives(app, tmp_path):
    bad_path = tmp_path / "directory"
    bad_path.mkdir()
    window = MainWindow(bad_path)
    try:
        wait_for(app, lambda: bool(window.error_label.text()))
        assert not window.start_button.isEnabled()
        assert "التخزين" in window.error_label.text()
    finally:
        window.close()
        wait_for(app, lambda: not window.worker.isRunning())
