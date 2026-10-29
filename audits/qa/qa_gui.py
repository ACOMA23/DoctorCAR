"""QA-UI: drive the real MainWindow on the native Windows Qt platform with QTest input.

Interaction is Qt-level (QTest mouse/keyboard events on the real widgets), not OS-level UI
Automation. Screenshots are QWidget.grab() renders of the real window, never mockups.
"""

import os
import re
import sys
import time
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)  # native "windows" platform, not offscreen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit,
    QListWidget, QPushButton, QSlider, QSpinBox, QTableWidget, QTabWidget, QTextEdit, QWidget,
)

from doctorcar.ui.main_window import MainWindow  # noqa: E402

ARABIC = re.compile(r"[؀-ۿ]")
SHOTS = EVIDENCE / "gate2" / "screenshots"
reg = Registry("gate2")
app = QApplication.instance() or QApplication([])
reg.environment = {"qt_platform": app.platformName(), "interaction": "QTest events on real widgets"}


def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.005)
    return bool(until and until())


def shot(window: QWidget, name: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"
    assert window.grab().save(str(path)), path
    return rel(path)


def click(widget: QWidget) -> None:
    assert widget.isEnabled(), f"{widget!r} is disabled"
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    pump(0.05)


def texts(window: MainWindow) -> list[tuple[str, str, str]]:
    found = []
    for w in window.findChildren(QWidget):
        kind = type(w).__name__
        name = w.objectName() or kind
        if isinstance(w, (QLabel, QAbstractButton)):
            found.append((name, kind, w.text()))
        if isinstance(w, QComboBox):
            found += [(name, kind, w.itemText(i)) for i in range(w.count())]
        if isinstance(w, QListWidget):
            found += [(name, kind, w.item(i).text()) for i in range(w.count())]
        if isinstance(w, QTableWidget):
            found += [(name, "header", w.horizontalHeaderItem(c).text())
                      for c in range(w.columnCount()) if w.horizontalHeaderItem(c)]
            found += [(name, "cell", w.item(r, c).text()) for r in range(w.rowCount())
                      for c in range(w.columnCount()) if w.item(r, c)]
        if w.toolTip():
            found.append((name, "tooltip", w.toolTip()))
    found.append(("window", "title", window.windowTitle()))
    return [t for t in found if t[2].strip()]


tmp = scratch("gui")
db = tmp / "gui-qa.sqlite3"
for leftover in tmp.glob("gui-qa*"):
    leftover.unlink()
t0 = time.monotonic()
window = MainWindow(db)
window.show()
ready = pump(until=lambda: window.backend_ready, limit=15)
reg.check("QA-APP-001", "FR-010", "Native window opens and backend becomes ready",
          "MainWindow(db in temp dir) .show()", "visible window; backend_ready within 15 s",
          window.isVisible() and ready, f"visible={window.isVisible()} ready={ready} platform={app.platformName()}",
          shot(window, "01-dashboard-ar-light"), started=t0)

# ---------------------------------------------------------------------------- inventory
classes = {"QPushButton": QPushButton, "QComboBox": QComboBox, "QCheckBox": QCheckBox,
           "QLineEdit": QLineEdit, "QSpinBox": QSpinBox, "QDoubleSpinBox": QDoubleSpinBox,
           "QSlider": QSlider, "QListWidget": QListWidget, "QTableWidget": QTableWidget,
           "QTextEdit": QTextEdit, "QTabWidget": QTabWidget}
inventory = {}
for label, cls in classes.items():
    inventory[label] = [
        {"name": w.objectName() or next((k for k, v in vars(window).items() if v is w), ""),
         "text": getattr(w, "text", lambda: "")() if hasattr(w, "text") else "",
         "enabled": w.isEnabled(), "items": (w.count() if hasattr(w, "count") else None)}
        for w in window.findChildren(cls)
    ]
inventory["menus"] = [a.text() for a in window.menuBar().actions()] if window.menuBar() else []
inventory["shortcuts"] = [a.shortcut().toString() for a in window.findChildren(__import__("PySide6.QtGui", fromlist=["QAction"]).QAction) if a.shortcut().toString()]
inventory["dialogs_in_code"] = ["QFileDialog.getOpenFileName (replay/protocol file)", "QFileDialog save (export session)"]
folder = EVIDENCE / "gate2"
folder.mkdir(parents=True, exist_ok=True)
import json  # noqa: E402

(folder / "ui-inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-UI-001", "FR-010", "UI element inventory extracted from the live window", "findChildren per class",
          "non-empty inventory; menus/shortcuts reported as found",
          len(inventory["QPushButton"]) > 5,
          "; ".join(f"{k}={len(v)}" for k, v in inventory.items()), rel(folder / "ui-inventory.json"),
          notes="No menu bar and no keyboard shortcuts exist in the product (reported, not a defect by itself).")

# ---------------------------------------------------------------------------- navigation
nav_ok, details = True, []
for row in range(window.navigation.count()):
    item = window.navigation.item(row)
    rect = window.navigation.visualItemRect(item)
    QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    pump(0.15)
    good = window.pages.currentIndex() == row and window.navigation.currentRow() == row
    nav_ok &= good
    details.append(f"{row}:{item.text()}={'ok' if good else 'BAD'}")
    shot(window, f"02-page{row}-ar-light")
reg.check("QA-UI-002", "FR-010", "Mouse navigation across all six pages", "click each sidebar row",
          "pages.currentIndex follows the clicked row", nav_ok, "; ".join(details),
          rel(SHOTS / "02-page5-ar-light.png"))

# ---------------------------------------------------------------------------- source center matrix
window.navigation.setCurrentRow(1)
sim_only = ["mode_combo", "family_combo", "scenario_combo", "fault_list", "multisensor_list",
            "variant_combo", "fault_start", "fault_duration", "severity_input", "max_faults_input",
            "normal_probability"]
expect = {
    "simulation": {"visible": ["mode_combo", "family_combo", "seed_input", "speed_combo"], "hidden": ["host_input", "network_port", "path_input", "port_combo"]},
    "replay": {"visible": ["path_input", "browse_button"], "hidden": sim_only + ["host_input", "network_port", "port_combo", "seed_input"]},
    "protocol_file": {"visible": ["path_input", "browse_button"], "hidden": sim_only + ["host_input", "network_port", "port_combo"]},
    "serial": {"visible": ["port_combo", "refresh_ports"], "hidden": sim_only + ["host_input", "network_port", "path_input", "seed_input", "speed_combo"]},
    "network": {"visible": ["host_input", "network_port"], "hidden": sim_only + ["port_combo", "path_input", "seed_input", "speed_combo"]},
}
bad = []
kinds = {}
for i in range(window.source_combo.count()):
    kinds[window.source_combo.itemData(i)] = i
for kind, rule in expect.items():
    window.source_combo.setCurrentIndex(kinds[kind])
    pump(0.1)
    for name in rule["visible"]:
        if not window.source_form.isRowVisible(getattr(window, name)):
            bad.append(f"{kind}: {name} should be visible")
    for name in rule["hidden"]:
        if window.source_form.isRowVisible(getattr(window, name)):
            bad.append(f"{kind}: {name} should be hidden")
    shot(window, f"03-source-{kind}")
dev_idx = kinds.get("device_simulator")
if dev_idx is not None:
    window.source_combo.setCurrentIndex(dev_idx)
    pump(0.1)
    leak = [n for n in sim_only if window.source_form.isRowVisible(getattr(window, n))]
    if leak:
        bad.append(f"device_simulator: simulation-only fields visible: {leak}")
reg.check("QA-UI-003", "UI-001", "Source center shows only fields relevant to the selected source",
          "select each of the sources in the combo", "no simulation settings for real-device sources; each source shows its own fields",
          not bad, "mismatches: " + (", ".join(bad) or "none"), rel(SHOTS / "03-source-network.png"))

# simulation mode sub-matrix
window.source_combo.setCurrentIndex(kinds["simulation"])
sub_bad = []
for mode_i in range(window.mode_combo.count()):
    window.mode_combo.setCurrentIndex(mode_i)
    for fam_i in range(window.family_combo.count()):
        window.family_combo.setCurrentIndex(fam_i)
        pump(0.03)
        mode, fam = window.mode_combo.currentData(), window.family_combo.currentData()
        multi = fam == "multisensor"
        want = {
            "scenario_combo": mode == "LEGACY",
            "fault_list": mode == "FAULT_INJECTION" and not multi,
            "multisensor_list": mode == "FAULT_INJECTION" and multi,
            "fault_start": mode == "FAULT_INJECTION",
            "max_faults_input": mode == "RANDOM_FAULTS",
            "normal_probability": mode == "RANDOM_FAULTS",
        }
        for name, vis in want.items():
            if window.source_form.isRowVisible(getattr(window, name)) != vis:
                sub_bad.append(f"{mode}/{fam}: {name} expected {vis}")
reg.check("QA-UI-004", "SIM-001..003", "Simulation sub-options follow mode and family",
          "iterate all mode x family combinations", "visibility matches the mode (faults, schedule, random settings)",
          not sub_bad, "mismatches: " + (", ".join(sub_bad[:8]) or "none"))

# ---------------------------------------------------------------------------- start/stop with real clicks
window.mode_combo.setCurrentIndex(0)
window.family_combo.setCurrentIndex(0)
modes = {window.mode_combo.itemData(i): i for i in range(window.mode_combo.count())}
fams = {window.family_combo.itemData(i): i for i in range(window.family_combo.count())}
window.family_combo.setCurrentIndex(fams["multisensor"])
window.mode_combo.setCurrentIndex(modes["NORMAL"])
for i in range(window.speed_combo.count()):
    if window.speed_combo.itemData(i) == 30:
        window.speed_combo.setCurrentIndex(i)
window.ai_enabled.setChecked(True)
window.seed_input.setValue(4100)
ticks = []
timer = QTimer()
timer.timeout.connect(lambda: ticks.append(time.monotonic()))
timer.start(10)
t0 = time.monotonic()
click(window.start_button)
running = pump(until=lambda: not window.source_combo.isEnabled(), limit=10)
dup_disabled = not window.start_button.isEnabled()
locked = not window.source_combo.isEnabled()
window.navigation.setCurrentRow(2)  # switch pages while data flows
pump(1.0)
first = [window.sensor_table.item(r, 2).text() if window.sensor_table.item(r, 2) else "" for r in range(window.sensor_table.rowCount())]
pump(1.5)
second = [window.sensor_table.item(r, 2).text() if window.sensor_table.item(r, 2) else "" for r in range(window.sensor_table.rowCount())]
shot(window, "04-sensors-running")
changed = sum(a != b for a, b in zip(first, second, strict=True))
reg.check("QA-UI-005", "NFR-001", "Start via button click: source locks, start disabled, values update while navigating",
          "click start (simulation NORMAL, 30x, AI on); switch to sensors page", "source combo locked, start disabled, sensor values change",
          running and dup_disabled and locked and changed >= 3,
          f"running={running} start_disabled={dup_disabled} source_locked={locked} sensors_changed={changed}",
          rel(SHOTS / "04-sensors-running.png"), started=t0)
status_run = window.status_label.text()
ai_text = window.ai_label.text()
click(window.stop_button)
stopped = pump(until=lambda: window.source_combo.isEnabled(), limit=10)
status_stop = window.status_label.text()
gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
reg.check("QA-UI-006", "NFR-001", "Stop via button: controls unlock and last data is labeled as stopped",
          "click stop", "source combo enabled; status says data is last received (not live)",
          stopped and "متوقف" in status_stop, f"stopped={stopped} status='{status_stop}' running_status='{status_run}'")
reg.check("QA-UI-007", "NFR-001", "GUI stays responsive during a 30x session with AI",
          "10 ms QTimer ticks during the session", "no gap > 1 s", bool(gaps) and max(gaps) < 1.0,
          f"ticks={len(ticks)} max_gap={max(gaps) if gaps else None:.3f}s")
reg.check("QA-UI-008", "AI-005", "AI status card shows state and model version while running",
          "read ai_label after the run", "contains 'AI:' and the model version", "AI:" in ai_text and "iforest" in ai_text,
          f"label='{ai_text}'")

# second session after the first
click(window.start_button) if window.start_button.isEnabled() else None
pump(2.0)
click(window.stop_button)
pump(until=lambda: window.source_combo.isEnabled(), limit=10)
reg.check("QA-UI-009", "NFR-001", "Second session can start and stop after the first",
          "start/stop again", "controls return to idle", window.source_combo.isEnabled() and window.start_button.isEnabled(),
          f"idle={window.source_combo.isEnabled()}")

# ---------------------------------------------------------------------------- fault run and report by real clicks
window.mode_combo.setCurrentIndex(modes["FAULT_INJECTION"])
pump(0.1)
for i in range(window.multisensor_list.count()):
    window.multisensor_list.item(i).setCheckState(Qt.CheckState.Unchecked)
window.multisensor_list.item(1).setCheckState(Qt.CheckState.Checked)  # S02
window.fault_start.setValue(60)
window.fault_duration.setValue(35)
t0 = time.monotonic()
click(window.start_button)
got = pump(until=lambda: window.events_table.rowCount() >= 1 and window.worker is not None and any(
    "COMPLETE" in (window.events_table.item(r, 3).text() if window.events_table.item(r, 3) else "") or
    "مكتمل" in "".join(window.events_table.item(r, c).text() for c in range(window.events_table.columnCount()) if window.events_table.item(r, c))
    for r in range(window.events_table.rowCount())), limit=90)
click(window.stop_button)
pump(until=lambda: window.source_combo.isEnabled(), limit=10)
window.navigation.setCurrentRow(3)
pump(0.3)
shot(window, "05-events")
rows = window.events_table.rowCount()
item = window.events_table.item(0, 0)
center = window.events_table.visualItemRect(item).center()
QTest.mouseClick(window.events_table.viewport(), Qt.MouseButton.LeftButton, pos=center)
pump(0.2)
QTest.mouseDClick(window.events_table.viewport(), Qt.MouseButton.LeftButton, pos=center)
opened = pump(until=lambda: window.pages.currentIndex() == 4 and bool(window.simple_report_text.toPlainText()), limit=15)
shot(window, "06-report-simple")
simple = window.simple_report_text.toPlainText()
reg.check("QA-UI-010", "UI-001", "Double-click an event row opens the report page with a simple report",
          "fault run S02 then double-click first event", "report page index 4 and non-empty simple report with AI section",
          opened and "ماذا حدث" in simple and "الذكاء الاصطناعي" in simple, f"events={rows} opened={opened} len={len(simple)}",
          rel(SHOTS / "06-report-simple.png"), started=t0)
click(window.technical_button) if not window.technical_button.isChecked() else None
pump(0.5)
shot(window, "07-report-technical")
reg.check("QA-UI-011", "UI-002", "Technical details button reveals technical report and plot",
          "click 'عرض التفاصيل الفنية'", "report_text and time_plot visible",
          window.report_text.isVisible() and window.time_plot.isVisible(),
          f"report_visible={window.report_text.isVisible()} plot_visible={window.time_plot.isVisible()}",
          rel(SHOTS / "07-report-technical.png"))

# ---------------------------------------------------------------------------- language/theme matrix
mixed = {}
settings_page = 5
for lang_i, lang in ((1, "en"), (0, "ar")):
    for theme_i, theme in ((0, "light"), (1, "dark")):
        window.language_combo.setCurrentIndex(lang_i)
        window.theme_combo.setCurrentIndex(theme_i)
        pump(0.3)
        for row in range(window.navigation.count()):
            window.navigation.setCurrentRow(row)
            pump(0.1)
            if row in (0, 3, 5):
                shot(window, f"08-{lang}-{theme}-page{row}")
        if lang == "en":
            window.navigation.setCurrentRow(4)
            mixed[theme] = [(n, k, t[:60]) for n, k, t in texts(window) if ARABIC.search(t)]
rtl_ar = window.layoutDirection() == Qt.LayoutDirection.RightToLeft
window.language_combo.setCurrentIndex(1)
pump(0.3)
ltr_en = window.layoutDirection() == Qt.LayoutDirection.LeftToRight
seen = {}
for n, k, t in mixed.get("light", []):
    seen.setdefault((k, t), n)
ui_arabic = [(k, t) for (k, t) in seen if k not in ("cell",)]
(folder / "english-mode-arabic-text.json").write_text(json.dumps(mixed, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-UI-012", "SETTINGS-001", "English mode contains no leftover Arabic UI text",
          "switch to EN, visit every page, scan labels/buttons/combos/lists/headers/tooltips",
          "no Arabic characters in controls (event cells and preserved diagnostic text excluded)",
          not ui_arabic, f"{len(ui_arabic)} Arabic strings in EN mode: " + "; ".join(f"{k}:{t[:30]}" for k, t in ui_arabic[:6]),
          rel(folder / "english-mode-arabic-text.json"))
reg.check("QA-UI-013", "SETTINGS-001", "Layout direction RTL in Arabic and LTR in English", "toggle language",
          "RTL then LTR", rtl_ar and ltr_en, f"ar_rtl={rtl_ar} en_ltr={ltr_en}")
window.language_combo.setCurrentIndex(1)
window.theme_combo.setCurrentIndex(1)
pump(0.5)
click(window.stop_button) if window.stop_button.isEnabled() else None

# ---------------------------------------------------------------------------- negative inputs in UI
window.language_combo.setCurrentIndex(0)
window.navigation.setCurrentRow(1)
neg = []
window.source_combo.setCurrentIndex(kinds["network"])
pump(0.1)
for host in ("999.999.1.1", "example.com", "", "192.168.1.5"):
    window.host_input.setText(host)
    window.network_port.setValue(9)
    try:
        window.error_label.hide()
        click(window.verify_button)
        pump(until=lambda: window.error_label.isVisible() or "فحص" in window.connection_details.text() or window.connection_details.text() != "DISCONNECTED", limit=12)
        neg.append((host, window.error_label.text()[:80], window.connection_details.text()[:60], window.isVisible()))
    except Exception as exc:  # noqa: BLE001
        neg.append((host, f"EXC {exc!r}", "", window.isVisible()))
reg.check("QA-UI-014", "CONN-001", "Invalid/unreachable network hosts are rejected without crash",
          "verify with 999.999.1.1, example.com, empty, 192.168.1.5", "an error is shown, window alive",
          all(n[3] and (n[1] or n[2]) for n in neg), " | ".join(f"{h!r}->{e or c}" for h, e, c, _ in neg))
window.source_combo.setCurrentIndex(kinds["replay"])
window.path_input.setText(str(tmp / "does-not-exist.jsonl"))
window.error_label.hide()
click(window.verify_button)
pump(until=lambda: window.error_label.isVisible(), limit=10)
reg.check("QA-UI-015", "CONN-001", "Missing replay file is reported", "verify nonexistent file", "error label visible",
          window.error_label.isVisible() and window.isVisible(), f"error='{window.error_label.text()[:90]}'")
window.source_combo.setCurrentIndex(kinds["replay"])
window.error_label.hide()
window.path_input.setText("")
try:
    click(window.start_button)
    pump(until=lambda: window.error_label.isVisible(), limit=8)
    reg.check("QA-UI-016", "UI-001", "Start with replay and no file shows an error",
              "start with empty path", "error visible and window alive", window.error_label.isVisible(),
              f"error='{window.error_label.text()[:90]}'")
except AssertionError as exc:
    reg.add("QA-UI-016", "UI-001", "Start with replay and no file", "start with empty path", "error visible", str(exc), "FAIL")
click(window.stop_button) if window.stop_button.isEnabled() else None

# ---------------------------------------------------------------------------- persistence and close
window.language_combo.setCurrentIndex(1)
window.theme_combo.setCurrentIndex(1)
pump(0.3)
window.close()
pump(until=lambda: window.worker.isFinished(), limit=10)
reg.check("QA-UI-017", "NFR-001", "Window close shuts the backend worker down", "close()", "worker finished",
          window.worker.isFinished(), f"worker_finished={window.worker.isFinished()}")
w2 = MainWindow(db)
w2.show()
pump(until=lambda: w2.backend_ready, limit=15)
rows2 = w2.events_table.rowCount()
reg.check("QA-UI-018", "SETTINGS-001", "Reopening restores language/theme and previous events",
          "new MainWindow on the same DB", "language=en theme=dark and the earlier events listed",
          w2.language == "en" and w2.theme == "dark" and rows2 >= 1, f"language={w2.language} theme={w2.theme} events={rows2}",
          shot(w2, "09-reopened-en-dark"))
# previous-session data must not look live
w2.navigation.setCurrentRow(2)
pump(0.3)
age = w2.age.text()
reg.check("QA-UI-019", "DATA-001", "Previous session data is not shown as live after restart",
          "read the data-age label after reopening", "no live reading claim (no data yet)",
          "No reading" in age or "لا توجد" in age or age.strip() in ("", "—"), f"age='{age}' context='{w2.context.text()[:60]}'")
w2.close()
pump(until=lambda: w2.worker.isFinished(), limit=10)
timer.stop()
reg.save()
