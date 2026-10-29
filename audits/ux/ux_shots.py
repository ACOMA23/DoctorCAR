"""DC-UX-001 screenshot capture of the real application (native Qt platform, temp DB only).

Every image is a render of the running MainWindow (QWidget.grab) or a Windows PrintWindow capture of the
application window itself. Nothing is drawn by this script. Usage: ux_shots.py <out_dir>
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from doctorcar.ui.main_window import MainWindow  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
shots: list[str] = []


def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.004)
    return bool(until and until())


def idx(combo, data):
    return next(i for i in range(combo.count()) if combo.itemData(i) == data)


def grab(name):
    pump(0.25)
    path = out / f"{name}.png"
    assert w.grab().save(str(path)), path
    shots.append(name)


def printwindow(name):
    pump(0.25)
    path = out / f"os-{name}.png"
    hwnd = int(w.winId())
    g = w.frameGeometry()
    ps = (
        "Add-Type -AssemblyName System.Drawing;"
        "Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;"
        "public class PW{[DllImport(\"user32.dll\")]public static extern bool PrintWindow(IntPtr h,IntPtr d,uint f);}';"
        f"$b=New-Object System.Drawing.Bitmap({g.width()},{g.height()});$gr=[System.Drawing.Graphics]::FromImage($b);$dc=$gr.GetHdc();"
        f"$ok=[PW]::PrintWindow([IntPtr]{hwnd},$dc,2);$gr.ReleaseHdc($dc);$b.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$gr.Dispose();$b.Dispose();if(-not $ok){exit 3}"
    )
    proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    end = time.monotonic() + 40
    while proc.poll() is None and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    assert proc.poll() == 0, "PrintWindow failed"
    shots.append("os-" + name)


db = Path(tempfile.mkdtemp(prefix="dc-ux-shots-")) / "shots.sqlite3"
w = MainWindow(db)
w.resize(1280, 720)
w.show()
pump(until=lambda: w.backend_ready, limit=20)
pump(0.6)
w.language_combo.setCurrentIndex(0)
w.theme_combo.setCurrentIndex(0)
grab("01-dashboard-empty-ar-light")
w.navigation.setCurrentRow(2)
grab("02-sensors-empty-ar-light")
w.navigation.setCurrentRow(3)
grab("03-events-empty-ar-light")
w.navigation.setCurrentRow(4)
grab("04-report-empty-ar-light")

# --- run a multisensor fault session with AI on
w.navigation.setCurrentRow(1)
w.family_combo.setCurrentIndex(idx(w.family_combo, "multisensor"))
w.mode_combo.setCurrentIndex(idx(w.mode_combo, "FAULT_INJECTION"))
pump(0.1)
for i in range(w.multisensor_list.count()):
    w.multisensor_list.item(i).setCheckState(Qt.CheckState.Checked if i == 0 else Qt.CheckState.Unchecked)
w.multisensor_list.setCurrentRow(0)
w.fault_start.setValue(60)
w.fault_duration.setValue(35)
w.seed_input.setValue(4100)
w.speed_combo.setCurrentIndex(idx(w.speed_combo, 10))
w.ai_enabled.setChecked(True)
grab("05-sources-sim-ar-light")
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
pump(until=lambda: w.latest is not None and w.latest.timestamp_ms > 30000, limit=60)
w.navigation.setCurrentRow(0)
grab("06-dashboard-receiving-ar-light")
printwindow("06-dashboard-receiving-ar-light")
w.navigation.setCurrentRow(2)
grab("07-sensors-cards-ar-light")
printwindow("07-sensors-cards-ar-light")
w.set_sensor_view(1)
grab("08-sensors-table-ar-light")
w.set_sensor_view(0)
pump(until=lambda: not w.running, limit=90)
pump(1.0)
w.navigation.setCurrentRow(0)
grab("09-dashboard-ended-ar-light")
w.navigation.setCurrentRow(1)
grab("10-sources-summary-ar-light")
w.navigation.setCurrentRow(3)
grab("11-events-ar-light")
printwindow("11-events-ar-light")
w.events_table.selectRow(0)
w.open_event(0, 0)
pump(until=lambda: bool(w.simple_report_text.toPlainText()) and w.pages.currentIndex() == 4, limit=15)
pump(0.6)
grab("12-report-simple-ar-light")
printwindow("12-report-simple-ar-light")
w.technical_button.setChecked(True)
pump(0.4)
grab("13-report-technical-ar-light")

# --- language / theme matrix at 1280x720
for lang, lname in ((0, "ar"), (1, "en")):
    for theme, tname in ((0, "light"), (1, "dark")):
        w.language_combo.setCurrentIndex(lang)
        w.theme_combo.setCurrentIndex(theme)
        pump(0.4)
        for row, pname in enumerate(("dashboard", "sources", "sensors", "events", "report", "settings")):
            w.navigation.setCurrentRow(row)
            grab(f"m-{lname}-{tname}-{row}-{pname}")
w.technical_button.setChecked(False)

# --- sizes and zoom
w.language_combo.setCurrentIndex(0)
w.theme_combo.setCurrentIndex(0)
for (width, height) in ((1366, 768), (1920, 1080), (980, 640)):
    w.resize(width, height)
    pump(0.4)
    for row, pname in ((0, "dashboard"), (2, "sensors"), (3, "events")):
        w.navigation.setCurrentRow(row)
        grab(f"s-{width}x{height}-{pname}")
w.resize(1280, 720)
for zoom in (125, 150):
    w.zoom_combo.setCurrentIndex(idx(w.zoom_combo, zoom))
    pump(0.4)
    w.navigation.setCurrentRow(0)
    grab(f"z-{zoom}-dashboard")
    w.navigation.setCurrentRow(2)
    grab(f"z-{zoom}-sensors")
w.zoom_combo.setCurrentIndex(idx(w.zoom_combo, 100))

# --- collapsed sidebar, RTL and LTR
w.navigation.setCurrentRow(0)
w.set_sidebar_collapsed(True)
grab("c-collapsed-ar")
w.language_combo.setCurrentIndex(1)
pump(0.3)
grab("c-collapsed-en")
w.set_sidebar_collapsed(False)

# --- keyboard focus indicators
w.language_combo.setCurrentIndex(0)
w.navigation.setCurrentRow(0)
w.navigation.setFocus()
grab("f-focus-navigation")
w.dash_start.setFocus(Qt.FocusReason.TabFocusReason)
grab("f-focus-dashboard-button")
w.navigation.setCurrentRow(1)
w.source_combo.setFocus(Qt.FocusReason.TabFocusReason)
grab("f-focus-source-combo")
w.language_combo.setCurrentIndex(1)

# --- toast
w.notify("success", "تم نسخ النص إلى الحافظة")
w.notify("warning", "فُقد اتصال المصدر أو توقف؛ القراءات المعروضة ليست حية")
grab("t-toasts-en")
w.close()
pump(until=lambda: w.worker.isFinished(), limit=10)
print("captured", len(shots))
(out / "INDEX.txt").write_text("\n".join(shots), encoding="utf8")
