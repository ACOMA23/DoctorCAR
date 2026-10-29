"""Diagnostic (not a pass/fail test): reproduce QA-UI-005 first-start failure and print what the UI says."""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from doctorcar.ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.005)
    return bool(until and until())


tmp = Path(tempfile.mkdtemp(prefix="dc-diag-"))
w = MainWindow(tmp / "d.sqlite3")
w.show()
pump(until=lambda: w.backend_ready, limit=15)
fams = {w.family_combo.itemData(i): i for i in range(w.family_combo.count())}
modes = {w.mode_combo.itemData(i): i for i in range(w.mode_combo.count())}
w.family_combo.setCurrentIndex(fams["multisensor"])
w.mode_combo.setCurrentIndex(modes["NORMAL"])
for i in range(w.speed_combo.count()):
    if w.speed_combo.itemData(i) == 30:
        w.speed_combo.setCurrentIndex(i)
w.ai_enabled.setChecked(True)
w.seed_input.setValue(4100)
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
for t in range(8):
    pump(1.0)
    print(t, "locked=", not w.source_combo.isEnabled(), "start_en=", w.start_button.isEnabled(),
          "status=", w.status_label.text(), "| err_visible=", w.error_label.isVisible(), w.error_label.text(),
          "| ai=", w.ai_label.text(), flush=True)
QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton) if w.stop_button.isEnabled() else None
pump(2.0)
w.close()
pump(until=lambda: w.worker.isFinished(), limit=10)
