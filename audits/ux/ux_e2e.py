"""QA-E2E 01-05, 08, 09, 11: scenarios driven through the real MainWindow (native platform)."""

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qa"))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from doctorcar.ui.main_window import MainWindow  # noqa: E402

reg = Registry("gate10")
folder = EVIDENCE / "gate10"
shots = folder / "screenshots"
shots.mkdir(parents=True, exist_ok=True)
tmp = scratch("e2e")
app = QApplication.instance() or QApplication([])


def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.004)
    return bool(until and until())


def shot(w, name):
    p = shots / f"{name}.png"
    w.grab().save(str(p))
    return rel(p)


def click(btn):
    assert btn.isEnabled()
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    pump(0.05)


def fresh_db(name):
    for f in tmp.glob(f"{name}.*"):
        f.unlink()
    return tmp / f"{name}.sqlite3"


def open_window(db):
    w = MainWindow(db)
    w.show()
    assert pump(until=lambda: w.backend_ready, limit=15)
    return w


def combo_index(combo, data):
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            return i
    raise KeyError(data)


def configure(w, mode, scenario_rows=(), start=60, dur=35, seed=4100, ai=True, severity=1.0):
    w.navigation.setCurrentRow(1)
    w.source_combo.setCurrentIndex(combo_index(w.source_combo, "simulation"))
    w.family_combo.setCurrentIndex(combo_index(w.family_combo, "multisensor"))
    w.mode_combo.setCurrentIndex(combo_index(w.mode_combo, mode))
    pump(0.05)
    for i in range(w.multisensor_list.count()):
        w.multisensor_list.item(i).setCheckState(Qt.CheckState.Checked if i in scenario_rows else Qt.CheckState.Unchecked)
    w.fault_start.setValue(start)
    w.fault_duration.setValue(dur)
    w.severity_input.setValue(severity)
    w.seed_input.setValue(seed)
    w.speed_combo.setCurrentIndex(combo_index(w.speed_combo, 30))
    w.ai_enabled.setChecked(ai)


def latest_session(con):
    return con.execute("select session_id from sessions order by started_at_ms desc limit 1").fetchone()[0]


def run_to_end(w, db, target=776, limit=120):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    click(w.start_button)
    pump(until=lambda: not w.source_combo.isEnabled(), limit=15)

    def done():
        try:
            return con.execute("select count(*) from measurements where session_id=?", (latest_session(con),)).fetchone()[0] >= target
        except (sqlite3.Error, TypeError):
            return False

    ok = pump(until=done, limit=limit)
    pump(1.0)
    click(w.stop_button) if w.stop_button.isEnabled() else None
    pump(until=lambda: w.source_combo.isEnabled(), limit=20)
    pump(0.5)
    n = con.execute("select count(*) from measurements where session_id=?", (latest_session(con),)).fetchone()[0]
    events = con.execute("select event_id, kind, trigger_ms, status from events where session_id=? order by trigger_ms", (latest_session(con),)).fetchall()
    sess = latest_session(con)
    con.close()
    return ok, n, events, sess


def open_report(w, row):
    w.navigation.setCurrentRow(3)
    pump(0.3)
    item = w.events_table.item(row, 0)
    pos = w.events_table.visualItemRect(item).center()
    QTest.mouseClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    pump(0.2)
    QTest.mouseDClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    pump(until=lambda: w.pages.currentIndex() == 4 and bool(w.simple_report_text.toPlainText()), limit=15)
    pump(0.3)
    return w.simple_report_text.toPlainText()


def row_of(w, kind_text):
    for r in range(w.events_table.rowCount()):
        if kind_text in w.events_table.item(r, 0).text():
            return r
    return 0


# ------------------------------------------------------------------ E2E-01 normal trips
results01 = []
for seed in (42, 777, 2026, 4100):
    db = fresh_db(f"e2e01-{seed}")
    w = open_window(db)
    configure(w, "NORMAL", seed=seed)
    ok, n, events, _ = run_to_end(w, db)
    results01.append({"seed": seed, "samples": n, "events": [(e[1], e[2] / 1000) for e in events], "finished": ok})
    if seed == 42:
        w.navigation.setCurrentRow(2)
        pump(0.3)
        shot(w, "e2e01-normal-sensors")
    w.close()
    pump(until=lambda: w.worker.isFinished(), limit=15)
(folder / "e2e01.json").write_text(json.dumps(results01, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-E2E-001", "AT-MS-01", "Normal trip from the app: start, readings, ML on, finish; no unjustified alarms (4 seeds, default scale)",
          "GUI: simulation NORMAL, AI on, seeds 42/777/2026/4100", "776 samples each and zero events", all(r["finished"] and r["samples"] >= 776 and not r["events"] for r in results01), json.dumps(results01, ensure_ascii=False),
          rel(folder / "e2e01.json"), notes="Driving scale/warm start are not exposed in the UI, so the high-scale cold-start weakness (QA-AI-011) cannot be reproduced through the GUI.")

# ------------------------------------------------------------------ E2E-02/03/09 single-scenario sessions with reports
reports = {}
for tag, rows, kind, seed in (("e2e02-thermal-S01", (0,), "MS_THERMAL", 4100), ("e2e03-airfuel-S02", (1,), "MS_AIR_FUEL", 4100), ("e2e09-supply-S05", (4,), "MS_SUPPLY", 4100)):
    db = fresh_db(tag)
    w = open_window(db)
    configure(w, "FAULT_INJECTION", rows, 60, 35, seed)
    ok, n, events, sess = run_to_end(w, db)
    kinds = [e[1] for e in events]
    row = row_of(w, "") if not kinds else 0
    # choose the row of the expected rule event if present
    for r in range(w.events_table.rowCount()):
        if w.events_table.item(r, 8) and kind in " ".join(w.events_table.item(r, c).text() for c in range(9)):
            row = r
    w.navigation.setCurrentRow(3)
    pump(0.3)
    shot(w, f"{tag}-events")
    simple = open_report(w, row) if w.events_table.rowCount() else ""
    shot(w, f"{tag}-report")
    click(w.technical_button) if not w.technical_button.isChecked() else None
    pump(0.5)
    tech = w.report_text.toPlainText()
    shot(w, f"{tag}-technical")
    (folder / f"{tag}-simple-ar.txt").write_text(simple, encoding="utf8")
    (folder / f"{tag}-technical.txt").write_text(tech, encoding="utf8")
    reports[tag] = {"samples": n, "events": [(e[1], e[2] / 1000, e[3]) for e in events], "has_rule_event": kind in kinds, "simple_chars": len(simple), "tech_chars": len(tech),
                    "simple": simple, "tech": tech, "ai_label": w.ai_label.text()}
    w.close()
    pump(until=lambda: w.worker.isFinished(), limit=15)
r = reports["e2e02-thermal-S01"]
reg.check("QA-E2E-002", "AT-MS-02", "Thermal rise through the app: detection, saved event, report with checks", "GUI: S01 at 60 s, AI on", "MS_THERMAL event COMPLETE; report lists cooling check; AI state stated; hedged",
          r["has_rule_event"] and "مستوى السائل" in r["simple"] and "اشتباه يحتاج تأكيدًا" in r["simple"] and "ماذا لاحظ الذكاء الاصطناعي" in r["simple"], f"events={r['events']}; chars={r['simple_chars']}", rel(folder / "e2e02-thermal-S01-simple-ar.txt"))
r = reports["e2e03-airfuel-S02"]
reg.check("QA-E2E-003", "AT-MS-03", "Air/fuel disturbance through the app: pattern detected, MAF/MAP evidence, readable report", "GUI: S02 at 60 s, AI on", "MS_AIR_FUEL event; technical report shows MAF and MAP residuals; simple report hedged",
          r["has_rule_event"] and "maf_residual_pct" in r["tech"].lower() and "map_residual" in r["tech"].lower() and "اشتباه يحتاج تأكيدًا" in r["simple"], f"events={r['events']}", rel(folder / "e2e03-airfuel-S02-technical.txt"))
r = reports["e2e09-supply-S05"]
has_xai = "العوامل الأكثر تأثيرًا" in r["simple"]
reg.check("QA-E2E-009", "AI-005/XAI-003", "ML + XAI with the real model through the app: an event whose AI result is anomalous shows computed XAI factors; otherwise the state is stated",
          "GUI: S05 (voltage) at 60 s, default model v3", "AI state in the report; if anomalous, factors line + 'not mechanical causes'; technical report lists XAI method and model version",
          "ماذا لاحظ الذكاء الاصطناعي" in r["simple"] and ("iforest-cr006-v3" in r["tech"]) and (not has_xai or "ليست أسبابًا ميكانيكية" in r["simple"]) and (not has_xai or "grouped-training-median-perturbation" in r["tech"]),
          f"xai_in_simple={has_xai}; model_in_technical={'iforest-cr006-v3' in r['tech']}; ai_label={r['ai_label']}", rel(folder / "e2e09-supply-S05-technical.txt"))

# ------------------------------------------------------------------ E2E-04 intermittent + E2E-08 restart restore
db = fresh_db("e2e04")
w = open_window(db)
configure(w, "FAULT_INJECTION", (5,), 60, 9, 4100)  # S06 intermittent combustion
ok, n, events, sess = run_to_end(w, db)
before_rows = w.events_table.rowCount()
mid = next((e for e in events if e[1] == "MS_COMBUSTION"), None)
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
lo, hi, cnt = con.execute("select min(m.timestamp_ms), max(m.timestamp_ms), count(*) from event_samples es join measurements m on m.session_id=es.session_id and m.sequence_number=es.sequence_number where es.event_id=?", (mid[0],)).fetchone() if mid else (None, None, 0)
con.close()
text_before = open_report(w, row_of(w, "")) if before_rows else ""
sess_before = {e[0] for e in events}
w.close()
pump(until=lambda: w.worker.isFinished(), limit=15)
reg.check("QA-E2E-004", "AT-MS-06", "Intermittent fault: it appears and disappears but recording continues to T+30 and the event is saved",
          "GUI: S06, 9 s", "MS_COMBUSTION COMPLETE with samples from T-30 to T+30", mid is not None and mid[3] == "COMPLETE" and lo == mid[2] - 30000 and hi == mid[2] + 30000,
          f"event={mid}; samples {lo}..{hi} n={cnt}")
w2 = open_window(db)
rows_after = w2.events_table.rowCount()
text_after = open_report(w2, row_of(w2, "")) if rows_after else ""
shot(w2, "e2e08-restored-report")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
sessions_after = con.execute("select count(*) from sessions").fetchone()[0]
con.close()
reg.check("QA-E2E-008", "AT-014", "Restart: events and reports are restored identically and sessions are not mixed", "close the app, reopen on the same database, open the same report",
          "same number of events, identical report text, one session", rows_after == before_rows and text_after == text_before and sessions_after == 1 and bool(text_after),
          f"events {before_rows}->{rows_after}; report identical={text_after == text_before}; sessions={sessions_after}", rel(shots / "e2e08-restored-report.png"))

# ------------------------------------------------------------------ E2E-11 language/theme then restart, old report in the other language
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def logical_hash():
    h = hashlib.sha256()
    for t in ("sessions", "measurements", "events", "event_samples", "diagnostic_reports"):
        for row in con.execute(f"select * from {t} order by 1,2"):
            h.update(repr(row).encode())
    return h.hexdigest()


h1 = logical_hash()
w2.language_combo.setCurrentIndex(combo_index(w2.language_combo, "en"))
w2.theme_combo.setCurrentIndex(combo_index(w2.theme_combo, "dark"))
pump(0.5)
text_en = open_report(w2, 0)
shot(w2, "e2e11-en-dark-report")
w2.close()
pump(until=lambda: w2.worker.isFinished(), limit=15)
w3 = open_window(db)
persisted = (w3.language, w3.theme)
text_en2 = open_report(w3, 0)
h2 = logical_hash()
w3.close()
pump(until=lambda: w3.worker.isFinished(), limit=15)
con.close()
reg.check("QA-E2E-011", "SETTINGS-001", "Language/theme change, restart, old report rendered in English; stored data unchanged", "EN + dark -> close -> reopen -> open an Arabic-era report",
          "settings persisted; English report text; database logical hash unchanged", persisted == ("en", "dark") and h1 == h2 and "What happened?" in text_en and text_en == text_en2,
          f"persisted={persisted}; english_report_ok={'What happened?' in text_en}; same_after_restart={text_en == text_en2}; db_hash_unchanged={h1 == h2}", rel(shots / "e2e11-en-dark-report.png"))

# ------------------------------------------------------------------ E2E-05 random faults, injected vs detected (QA-side comparison only)
db = fresh_db("e2e05")
w = open_window(db)
w.navigation.setCurrentRow(1)
w.source_combo.setCurrentIndex(combo_index(w.source_combo, "simulation"))
w.family_combo.setCurrentIndex(combo_index(w.family_combo, "multisensor"))
w.mode_combo.setCurrentIndex(combo_index(w.mode_combo, "RANDOM_FAULTS"))
pump(0.05)
w.seed_input.setValue(11)
w.max_faults_input.setValue(2)
w.normal_probability.setValue(0.25)
w.speed_combo.setCurrentIndex(combo_index(w.speed_combo, 30))
w.ai_enabled.setChecked(True)
ok, n, events, sess = run_to_end(w, db)
w.navigation.setCurrentRow(3)
pump(0.3)
shot(w, "e2e05-random-events")
w.close()
pump(until=lambda: w.worker.isFinished(), limit=15)
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
meta = json.loads(con.execute("select metadata_json from simulation_runs where session_id=?", (sess,)).fetchone()[0])
con.close()
cycles = meta.get("scenario_cycles", [])
injected = meta.get("scenarios") or meta.get("scenario_schedule") or []
cmp = {"cycles": len(cycles), "ground_truth_schedule": injected, "detected_events": [(e[1], e[2] / 1000) for e in events]}
rule_map = {"S01": "MS_THERMAL", "S02": "MS_AIR_FUEL", "S03": "MS_FUEL_RESPONSE", "S04": "MS_AIRFLOW", "S05": "MS_SUPPLY", "S06": "MS_COMBUSTION", "S07": "MS_SIGNAL"}
rows = []
for inst in injected:
    sid = inst.get("scenario_id")
    start, dur = inst["start_ms"], inst["duration_ms"]
    hit = [e for e in events if e[1] == rule_map.get(sid) and start <= e[2] <= start + dur + 10000]
    rows.append({"scenario": sid, "start_s": start / 1000, "duration_s": dur / 1000, "detected": bool(hit), "event": hit[0][1:3] if hit else None})
cmp["comparison"] = rows
(folder / "e2e05.json").write_text(json.dumps(cmp, ensure_ascii=False, indent=2, default=str), encoding="utf8")
reg.check("QA-E2E-005", "AT-003", "RANDOM_FAULTS through the app: 30 s cycles recorded as separate ground truth and compared with detections", "GUI: RANDOM_FAULTS seed 11, max 2 faults",
          "cycle schedule stored in simulation_runs; every injected instance listed with detected yes/no", bool(cycles) and bool(injected) and n >= 776,
          f"cycles={len(cycles)} injected={len(injected)} detected={sum(r['detected'] for r in rows)}/{len(rows)}; events={[(e[1], round(e[2] / 1000, 1)) for e in events]}", rel(folder / "e2e05.json"),
          notes="Ground truth lives only in simulation_runs and this QA comparison; the detectors never read it.")
reg.save()
