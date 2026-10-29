"""Render the real Qt application and backend to evidence PNGs, with no hardware."""

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from doctorcar.ui.main_window import MainWindow
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / "docs/evidence"
    target.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(root / "data" / f"preview-{time.time_ns()}.sqlite3")
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    started = time.monotonic()
    state = 0
    failed = False

    def capture() -> None:
        nonlocal state, failed
        if time.monotonic() - started > 40 and not failed:
            failed = True
            window.worker.shutdown()
            print("Preview timed out")
        if failed:
            if not window.worker.isRunning():
                app.exit(1)
            return
        if state == 0 and window.backend_ready:
            window.scenario_combo.setCurrentIndex(1)
            window.speed_combo.setCurrentIndex(2)
            window.start_button.click()
            state = 1
        elif (
            state == 1
            and window.latest is not None
            and window.latest.timestamp_ms >= 95000
        ):
            window.navigation.setCurrentRow(0)
            window.grab().save(str(target / "ui-dashboard.png"))
            state = 2
        elif (
            state == 2
            and window.latest is not None
            and window.latest.timestamp_ms >= 125000
        ):
            window.navigation.setCurrentRow(3)
            state = 3
        elif state == 3:
            window.grab().save(str(target / "ui-events.png"))
            window.open_event(0, 0)
            state = 4
        elif state == 4 and "حدود النتيجة" in window.report_text.toPlainText():
            window.grab().save(str(target / "ui-report.png"))
            window.navigation.setCurrentRow(2)
            state = 5
        elif state == 5:
            window.grab().save(str(target / "ui-sensors.png"))
            window.close()
            state = 6
        elif state == 6 and not window.worker.isRunning():
            print(f"Rendered dashboard/events/report/sensors to {target}")
            app.quit()

    timer = QTimer()
    timer.timeout.connect(capture)
    timer.start(50)
    code = app.exec()
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
