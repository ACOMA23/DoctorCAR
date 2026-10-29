"""DC-VERIFY-002: drive the real window to an event whose linked ML analysis is ANOMALOUS and check the XAI section (AR and EN)."""
import os, re, sys, time, json
from pathlib import Path
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qa"))
from qa_common import EVIDENCE, Registry, rel, scratch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from doctorcar.ui.main_window import MainWindow

reg = Registry("gui_xai")
folder = EVIDENCE / "gui_xai"; folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("gui-xai"); app = QApplication.instance() or QApplication([])
ARABIC = re.compile(r"[؀-ۿ]")
def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until(): return True
        time.sleep(0.004)
    return bool(until and until())
idx = lambda c, d: next(i for i in range(c.count()) if c.itemData(i) == d)
db = tmp / "x.sqlite3"
for f in tmp.glob("x.*"): f.unlink()
w = MainWindow(db); w.show(); pump(until=lambda: w.backend_ready, limit=20)
w.family_combo.setCurrentIndex(idx(w.family_combo, "multisensor")); w.mode_combo.setCurrentIndex(idx(w.mode_combo, "FAULT_INJECTION")); pump(0.1)
for i in range(w.multisensor_list.count()):
    w.multisensor_list.item(i).setCheckState(Qt.CheckState.Checked if w.multisensor_list.item(i).data(Qt.ItemDataRole.UserRole) == "S05" else Qt.CheckState.Unchecked)
w.fault_start.setValue(60); w.fault_duration.setValue(35); w.seed_input.setValue(4100); w.speed_combo.setCurrentIndex(idx(w.speed_combo, 30)); w.ai_enabled.setChecked(True)
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
pump(until=lambda: not w.source_combo.isEnabled(), limit=30)
pump(until=lambda: w.events_table.rowCount() >= 1, limit=120)
pump(until=lambda: any("مكتمل" in (w.events_table.item(r, 2).text() if w.events_table.item(r, 2) else "") for r in range(w.events_table.rowCount())), limit=60)
QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton); pump(until=lambda: w.source_combo.isEnabled(), limit=20); pump(0.5)
w.navigation.setCurrentRow(3); pump(0.2)
rows = [[(w.events_table.item(r, c).text() if w.events_table.item(r, c) else "") for c in range(9)] for r in range(w.events_table.rowCount())]
target = next((i for i, r in enumerate(rows) if "جهد" in r[0]), 0)  # the S05 supply-voltage event, not the data-quality rows
event_id = rows[target][3].strip("⁦⁩ ")
def open_first():
    w.simple_report_text.clear()
    it = w.events_table.item(target, 0)
    w.navigation.setCurrentRow(3); pump(0.2)
    QTest.mouseClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=w.events_table.visualItemRect(it).center()); pump(0.1)
    QTest.mouseDClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=w.events_table.visualItemRect(it).center())
    pump(until=lambda: bool(w.simple_report_text.toPlainText()), limit=15)
    return w.simple_report_text.toPlainText()
ar = open_first()
if not w.technical_button.isChecked(): QTest.mouseClick(w.technical_button, Qt.MouseButton.LeftButton)
pump(0.4); tech_ar = w.report_text.toPlainText()
w.language_combo.setCurrentIndex(1); pump(0.4)
en = open_first(); tech_en = w.report_text.toPlainText()
(folder / "xai-report-ar.txt").write_text(ar, encoding="utf8"); (folder / "xai-report-en.txt").write_text(en, encoding="utf8")
(folder / "xai-technical-en.txt").write_text(tech_en, encoding="utf8")
con = __import__("sqlite3").connect(f"file:{db}?mode=ro", uri=True)
rows_ai = con.execute("SELECT event_id, data_json FROM event_ai_status").fetchall()
ai_state = next((json.loads(j) for e, j in rows_ai if e == event_id), {})
(folder / "event-ai-status.json").write_text(json.dumps({"target_event": event_id, "target_row": target, "status": ai_state, "all": [[e, json.loads(j).get("state")] for e, j in rows_ai]}, ensure_ascii=False, indent=1), encoding="utf8")
anomalous = ai_state.get("state") == "ANALYZED_ANOMALOUS"
mech = "ليست أسبابًا ميكانيكية" in ar
mech_en = "not mechanical causes" in en.lower() or "not mechanical" in en.lower()
reg.check("QA-XAI-GUI-001", "XAI-001/003", "Window report for an event with an ANOMALOUS linked analysis shows the XAI factors and the 'not mechanical causes' caveat in Arabic and English; wording matches the stored decision",
          "S05 at 60 s, seed 4100, AI on (default model v3), open the event report, switch to EN", "stored status ANALYZED_ANOMALOUS <=> XAI section present in both languages",
          anomalous == (mech and mech_en) and bool(rows) and not ARABIC.search(en), f"stored_state={ai_state.get('state')}; ar_xai={mech}; en_xai={mech_en}; en_arabic_chars={len(ARABIC.findall(en))}; events={[r[:2] for r in rows]}", rel(folder / "event-ai-status.json"))
w.close(); pump(until=lambda: w.worker.isFinished(), limit=15)
reg.save()
