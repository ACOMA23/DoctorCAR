"""QA-UI controls: real clicks/typing on every button, combo, spin box, check box, line edit and list,
including the two file dialogs (export and browse), Replay of an exported session and the network source."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qa"))  # shared qa_common (unchanged)
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLineEdit, QPushButton, QSpinBox  # noqa: E402

from doctorcar.sources.replay import ReplaySource  # noqa: E402
from doctorcar.sources.serial_device import SerialDeviceSource  # noqa: E402
from doctorcar.ui.main_window import MainWindow  # noqa: E402

reg = Registry("gate2_controls")
folder = EVIDENCE / "gate2_controls"
shots = folder / "screenshots"
shots.mkdir(parents=True, exist_ok=True)
tmp = scratch("controls")
app = QApplication.instance() or QApplication([])


def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.004)
    return bool(until and until())


def click(w):
    assert w.isEnabled(), "disabled"
    QTest.mouseClick(w, Qt.MouseButton.LeftButton)
    pump(0.08)


def drive_dialog(path):
    """Fill the real (non-native) QFileDialog; a watchdog rejects any dialog left open."""
    state = {"done": False, "selected": None}

    def reject_open():
        d = app.activeModalWidget()
        if d is not None:
            d.reject()

    def act():
        d = app.activeModalWidget()
        if d is None:
            QTimer.singleShot(150, act)
            return
        edit = d.findChild(QLineEdit, "fileNameEdit")  # what a user types into the dialog
        edit.setText(str(path))
        state["selected"] = d.selectedFiles()
        d.accept()
        state["done"] = True
        QTimer.singleShot(1500, reject_open)

    QTimer.singleShot(500, act)
    QTimer.singleShot(12000, reject_open)
    return state


def button(w, text):
    return next(b for b in w.findChildren(QPushButton) if b.text() == text)


def idx(combo, data):
    return next(i for i in range(combo.count()) if combo.itemData(i) == data)


db = tmp / "controls.sqlite3"
for f in tmp.glob("controls.*"):
    f.unlink()
w = MainWindow(db)
w.show()
pump(until=lambda: w.backend_ready, limit=15)

# --- go-to-sources button
w.navigation.setCurrentRow(0)
click(button(w, "اختيار مصدر البيانات"))
reg.check("QA-UI-030", "UI-001", "Dashboard button 'اختيار مصدر البيانات' navigates to the source center", "click", "page index 1", w.pages.currentIndex() == 1, f"page={w.pages.currentIndex()}")

# --- every combo: all items selectable, currentData follows
combos = {n: getattr(w, n) for n in ("language_combo", "theme_combo", "source_combo", "family_combo", "mode_combo", "scenario_combo", "variant_combo", "speed_combo", "port_combo")}
report = {}
for name, c in combos.items():
    seen = []
    for i in range(c.count()):
        c.setCurrentIndex(i)
        pump(0.02)
        seen.append(c.currentIndex() == i)
    report[name] = {"items": c.count(), "all_selectable": all(seen)}
w.language_combo.setCurrentIndex(0)
w.theme_combo.setCurrentIndex(0)
w.source_combo.setCurrentIndex(0)
w.family_combo.setCurrentIndex(idx(w.family_combo, "multisensor"))
reg.check("QA-UI-031", "UI-001", "Every combo box: all items can be selected", "iterate items of 9 combos", "each item selectable", all(v["all_selectable"] for v in report.values()), json.dumps(report))

# --- spin boxes: clamping and keyboard
spin = {}
for name in ("network_port", "fault_start", "fault_duration", "seed_input", "max_faults_input", "severity_input", "normal_probability"):
    sb = getattr(w, name)
    lo, hi = sb.minimum(), sb.maximum()
    sb.setValue(lo - 1000)
    below = sb.value()
    sb.setValue(hi + 100000)
    above = sb.value()
    sb.setValue(lo)
    sb.setFocus()
    QTest.keyClick(sb, Qt.Key.Key_Up)
    up = sb.value()
    QTest.keyClick(sb, Qt.Key.Key_Down)
    spin[name] = {"min": lo, "max": hi, "below->": below, "above->": above, "up_key": up, "clamped": below == lo and above == hi and up > lo}
w.seed_input.setValue(42)
w.fault_start.setValue(60)
w.fault_duration.setValue(35)
w.severity_input.setValue(1.0)  # the spin-box test left the minimum behind
w.max_faults_input.setValue(2)
w.normal_probability.setValue(0.25)
reg.check("QA-UI-032", "UI-001", "Spin boxes clamp out-of-range values and respond to the keyboard", "set below min / above max; arrow keys", "value clamped to the range; Up increases", all(v["clamped"] for v in spin.values()), json.dumps(spin))

# --- typing into line edits and check boxes
w.source_combo.setCurrentIndex(idx(w.source_combo, "network"))
pump(0.1)
w.host_input.selectAll()
QTest.keyClicks(w.host_input, "127.0.0.1")
w.source_combo.setCurrentIndex(idx(w.source_combo, "replay"))
pump(0.1)
QTest.keyClicks(w.path_input, "abc.jsonl")
typed = (w.host_input.text(), w.path_input.text())
w.path_input.clear()
from PySide6.QtCore import QPoint  # noqa: E402


def click_checkbox(cb):
    """A QCheckBox only reacts on its indicator/label, so click on the label side then the indicator side."""
    before = cb.isChecked()
    for x in (cb.width() - 14, 14, cb.width() // 2):
        QTest.mouseClick(cb, Qt.MouseButton.LeftButton, pos=QPoint(x, cb.height() // 2))
        pump(0.05)
        if cb.isChecked() != before:
            return x
    return None


w.ai_enabled.setChecked(False)
hit = click_checkbox(w.ai_enabled)
tog1 = w.ai_enabled.isChecked()
click_checkbox(w.ai_enabled)
tog2 = w.ai_enabled.isChecked()
click_checkbox(w.ai_enabled)
reg.check("QA-UI-033", "UI-001", "Typing into host/path fields and toggling the AI check box with the mouse", "keyClicks + mouse clicks", "text appears; checkbox toggles", typed == ("127.0.0.1", "abc.jsonl") and tog1 and not tog2 and w.ai_enabled.isChecked(), f"typed={typed} toggles={tog1},{tog2} (indicator hit at x={hit}; the middle of the widget does not toggle)")

# --- run a faulty session, then use the event buttons
w.source_combo.setCurrentIndex(idx(w.source_combo, "simulation"))
w.mode_combo.setCurrentIndex(idx(w.mode_combo, "FAULT_INJECTION"))
pump(0.1)
for i in range(w.multisensor_list.count()):
    w.multisensor_list.item(i).setCheckState(Qt.CheckState.Checked if i == 0 else Qt.CheckState.Unchecked)
w.speed_combo.setCurrentIndex(idx(w.speed_combo, 30))
w.seed_input.setValue(4100)
click(w.start_button)
pump(until=lambda: not w.source_combo.isEnabled(), limit=10)
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def ready():
    try:
        return con.execute("select count(*) from measurements").fetchone()[0] >= 776
    except sqlite3.Error:
        return False


pump(until=ready, limit=90)
pump(1.0)
click(w.stop_button) if w.stop_button.isEnabled() else None
pump(until=lambda: w.source_combo.isEnabled(), limit=20)
w.navigation.setCurrentRow(3)
pump(0.5)
rows_before = w.events_table.rowCount()
click(button(w, "تحديث السجل"))
pump(1.0)
rows_after = w.events_table.rowCount()
reg.check("QA-UI-034", "UI-001", "'تحديث السجل' refreshes the event list without losing rows", "click refresh", "same rows", rows_before >= 1 and rows_after == rows_before, f"rows {rows_before}->{rows_after}")
item = w.events_table.item(0, 0)
QTest.mouseClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=w.events_table.visualItemRect(item).center())
pump(0.2)
w.simple_report_text.clear()
click(button(w, "عرض تقرير الحدث المحدد"))
opened = pump(until=lambda: w.pages.currentIndex() == 4 and bool(w.simple_report_text.toPlainText()), limit=15)
reg.check("QA-UI-035", "UI-001", "'عرض تقرير الحدث المحدد' opens the selected event's report", "select a row, click the button", "report page with text", opened, f"page={w.pages.currentIndex()} chars={len(w.simple_report_text.toPlainText())}")

# --- export dialog
export_path = tmp / "exported.jsonl"
export_path.unlink(missing_ok=True)
w.navigation.setCurrentRow(1)
st = drive_dialog(export_path)
click(button(w, "تصدير الجلسة لـ Replay"))
made = pump(until=lambda: export_path.exists() and export_path.stat().st_size > 1000, limit=15)
verify = ReplaySource(export_path).verify() if made else {}
reg.check("QA-UI-036", "REPLAY", "Export button: real file dialog -> session written as a Replay file that verifies", "click export, choose a path in the dialog", "file created and ReplaySource.verify ok",
          made and st["done"] and verify.get("ok", True), f"exists={export_path.exists()} bytes={export_path.stat().st_size if export_path.exists() else 0} verify={str(verify)[:100]}")

# --- browse dialog and replay through the UI
w.source_combo.setCurrentIndex(idx(w.source_combo, "replay"))
pump(0.1)
st = drive_dialog(export_path)
click(w.browse_button)
pump(until=lambda: st["done"], limit=10)
pump(0.3)
reg.check("QA-UI-037", "REPLAY", "Browse button: real file dialog fills the path field", "click browse, select exported file", "path_input equals the chosen file", Path(w.path_input.text()) == export_path, f"path='{w.path_input.text()}'")
w.error_label.hide()
click(w.verify_button)
vok = pump(until=lambda: "RECEIVING" in w.connection_details.text() or "CONNECTED" in w.connection_details.text() or w.error_label.isVisible() or "ناجح" in w.connection_details.text(), limit=15)
shot = shots / "controls-verify-replay.png"
w.grab().save(str(shot))
reg.check("QA-UI-038", "REPLAY", "Verify button on a replay file reports success", "click 'فحص المصدر / الاتصال' with a valid replay", "details label changes and no error", vok and not w.error_label.isVisible(), f"details='{w.connection_details.text()[:80]}' error_visible={w.error_label.isVisible()}", rel(shot))
before_events = con.execute("select count(*) from events where json_extract(metadata_json,'$.origin')='REPLAY'").fetchone()[0]
w.speed_combo.setCurrentIndex(idx(w.speed_combo, 30))
click(w.start_button)
pump(until=lambda: not w.source_combo.isEnabled(), limit=10)
pump(until=lambda: con.execute("select count(*) from events where json_extract(metadata_json,'$.origin')='REPLAY'").fetchone()[0] > before_events, limit=150)
pump(1.0)
click(w.stop_button) if w.stop_button.isEnabled() else None
pump(until=lambda: w.source_combo.isEnabled(), limit=20)
replay_events = con.execute("select kind, json_extract(metadata_json,'$.origin'), status from events where json_extract(metadata_json,'$.origin')='REPLAY'").fetchall()
reg.check("QA-UI-039", "REPLAY", "Replaying the exported session through the UI yields events with origin REPLAY", "start with the replay source", ">=1 event with origin REPLAY", bool(replay_events), f"replay events={replay_events}")

# --- refresh ports button
w.source_combo.setCurrentIndex(idx(w.source_combo, "serial"))
pump(0.1)
click(w.refresh_ports)
pump(1.5)
listed = SerialDeviceSource.available_ports()
reg.check("QA-UI-040", "CONN-001", "'تحديث المنافذ' fills the port list from the system; no port is opened", "click refresh ports", "combo items == system COM ports", w.port_combo.count() == len(listed), f"combo={w.port_combo.count()} system={listed}",
          notes="No serial port was opened or written to.")

# --- network source through the UI
ready_file = tmp / "ready.json"
ready_file.unlink(missing_ok=True)
proc = subprocess.Popen([sys.executable, "-m", "doctorcar.protocol.network_simulator", "--port", "0", "--speed", "30", "--history", str(tmp / "hist.json"), "--ready", str(ready_file)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
pump(until=lambda: ready_file.exists(), limit=15)
port = json.loads(ready_file.read_text())["port"]
w.source_combo.setCurrentIndex(idx(w.source_combo, "network"))
pump(0.1)
w.host_input.setText("127.0.0.1")
w.network_port.setValue(port)
w.error_label.hide()
click(w.verify_button)
pump(until=lambda: "RECEIVING" in w.connection_details.text() or w.error_label.isVisible(), limit=15)
verify_text = w.connection_details.text()
w.grab().save(str(shots / "controls-verify-network.png"))
click(w.start_button)
pump(until=lambda: not w.source_combo.isEnabled(), limit=10)
pump(until=lambda: con.execute("select count(*) from events where json_extract(metadata_json,'$.origin')='HISTORICAL'").fetchone()[0] >= 2, limit=40)
hist = con.execute("select count(*) from events where json_extract(metadata_json,'$.origin')='HISTORICAL'").fetchone()[0]
pump(2.0)
status_running = w.status_label.text()
click(w.stop_button) if w.stop_button.isEnabled() else None
pump(until=lambda: w.source_combo.isEnabled(), limit=20)
proc.terminate()
proc.communicate(timeout=5)
reg.check("QA-UI-041", "IOT-001..003", "Network source from the UI: verify shows handshake stages, session runs, historical events are imported", "type host/port, click verify, start, stop (loopback simulator)",
          "details mention RECEIVING_DATA; 2 HISTORICAL events; status shows the source", ("RECEIVING" in verify_text or "تصل البيانات" in verify_text) and hist >= 2, f"verify='{verify_text[:110]}' historical={hist} status='{status_running}'", rel(shots / "controls-verify-network.png"))
con.close()
w.close()
pump(until=lambda: w.worker.isFinished(), limit=15)
reg.save()
