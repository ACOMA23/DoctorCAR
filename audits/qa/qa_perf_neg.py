"""QA-PERF / QA-SEC negative: long run with measurements, GUI stress while data flows, negative inputs."""

import ctypes
import json
import os
import statistics
import sys
import time
from ctypes import wintypes
from dataclasses import asdict
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from doctorcar.analysis.analyzer import AnomalyAnalyzer  # noqa: E402
from doctorcar.analysis.explanation import explain  # noqa: E402
from doctorcar.analysis.model import AnomalyModel  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.sources.replay import ReplaySource  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402
from doctorcar.ui.main_window import MainWindow  # noqa: E402

reg = Registry("gate8")
folder = EVIDENCE / "gate8"
folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("perf")
app = QApplication.instance() or QApplication([])


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_psapi, _kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
_kernel.GetCurrentProcess.restype = wintypes.HANDLE
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def rss_mb():
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    assert _psapi.GetProcessMemoryInfo(_kernel.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb), "memory probe failed"
    return pmc.WorkingSetSize / 1e6


def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.003)
    return bool(until and until())


# ---------------------------------------------------------------------------- long run: 12 consecutive real trips
TRIPS = 12
db = tmp / "long.sqlite3"
for f in tmp.glob("long.sqlite3*"):
    f.unlink()
save_times, mem, inf_all = [], [], []
wall0, cpu0 = time.monotonic(), time.process_time()
accepted = rejected = generated = 0
with SQLiteRepository(db) as repo:
    original = repo.save_event

    def timed(event):
        t = time.perf_counter()
        original(event)
        save_times.append((time.perf_counter() - t) * 1000)

    repo.save_event = timed  # type: ignore[method-assign]
    mem.append((0, rss_mb()))
    for trip in range(TRIPS):
        src = SimulationSource(seed=2026 + trip, scenario_family="multisensor", mode="RANDOM_FAULTS", max_faults=2, normal_probability=0.3)
        analyzer = AnomalyAnalyzer()
        session = Session(src, repo, analyzer=analyzer)
        session.start()
        while not src.exhausted:
            session.step()
            generated += 1
        session.stop()
        accepted += session.accepted
        rejected += session.rejected
        inf_all += [r["inference_ms"] for r in analyzer.history if "inference_ms" in r]
        mem.append((generated, rss_mb()))
    n_events = repo.connection.execute("select count(*) from events").fetchone()[0]
    statuses = dict(repo.connection.execute("select status, count(*) from events group by status").fetchall())
    kinds = dict(repo.connection.execute("select kind, count(*) from events group by kind").fetchall())
    integrity = repo.connection.execute("pragma integrity_check").fetchone()[0]
    n_sessions = repo.connection.execute("select count(*) from sessions").fetchone()[0]
wall, cpu = time.monotonic() - wall0, time.process_time() - cpu0
size_mb = sum(f.stat().st_size for f in tmp.glob("long.sqlite3*")) / 1e6
expected = TRIPS * 776
SIM_SECONDS = TRIPS * 155
growth = mem[-1][1] - mem[1][1]
perf = {"trips": TRIPS, "simulated_seconds": SIM_SECONDS, "samples_generated": generated, "samples_accepted": accepted, "samples_rejected": rejected, "expected_samples": expected,
        "wall_s": round(wall, 1), "cpu_s": round(cpu, 1), "throughput_samples_per_s": round(accepted / wall, 1), "realtime_factor": round(SIM_SECONDS / wall, 1),
        "sessions": n_sessions, "events": n_events, "event_status": statuses, "event_kinds": kinds, "event_save_ms_median": round(statistics.median(save_times), 2),
        "event_save_ms_p95": round(sorted(save_times)[int(len(save_times) * 0.95)], 2), "event_save_ms_max": round(max(save_times), 2),
        "ml_inference_ms_median": round(statistics.median(inf_all), 2), "ml_inference_ms_p95": round(sorted(inf_all)[int(len(inf_all) * 0.95)], 2),
        "memory_mb_after_trip1": round(mem[1][1], 1), "memory_mb_end": round(mem[-1][1], 1), "memory_growth_mb_after_trip1": round(growth, 1), "db_size_mb": round(size_mb, 1),
        "db_growth_mb_per_simulated_hour": round(size_mb / (SIM_SECONDS / 3600), 1), "integrity": integrity, "memory_curve": [(n, round(m, 1)) for n, m in mem]}
(folder / "long-run.json").write_text(json.dumps(perf, indent=2), encoding="utf8")
reg.check("QA-PERF-001", "NFR-001", f"Long run: {TRIPS} consecutive RANDOM_FAULTS trips ({SIM_SECONDS} simulated s, 30 s cycles) with AI on; nothing dropped, integrity ok",
          "12 sessions x 155 s into one database", "all samples accepted, none rejected, integrity ok, realtime factor > 5",
          accepted == expected and rejected == 0 and integrity == "ok" and perf["realtime_factor"] > 5, json.dumps({k: v for k, v in perf.items() if k != "memory_curve"}), rel(folder / "long-run.json"))
reg.check("QA-PERF-002", "NFR-001", "Memory does not grow without bound across 12 sessions (process working set)", "psapi working set after each trip", "growth after the first trip < 150 MB",
          mem[1][1] > 50 and growth < 150, f"after trip 1: {perf['memory_mb_after_trip1']} MB; end: {perf['memory_mb_end']} MB; growth {perf['memory_growth_mb_after_trip1']} MB", rel(folder / "long-run.json"))
# one long single session: what happens beyond the 155 s driving profile?
src = SimulationSource(seed=7, scenario_family="multisensor", mode="RANDOM_FAULTS", duration_ms=600_000, max_faults=2, normal_probability=0.0)
src.connect()
src.start()
late_rpm = []
late_n = 0
while (smp := src.read_measurements()) is not None:
    if smp.timestamp_ms > 150_000:
        late_n += 1
        late_rpm.append(smp.readings["RPM"].value)
meta = src.get_simulation_metadata()
src.disconnect()
reg.check("QA-SIM-037", "SIM-003", "A simulation longer than the 155 s driving profile keeps producing driving data and periodic fault effects", "duration 600 s RANDOM_FAULTS, normal_probability 0",
          "engine keeps running (RPM > 0) so cycles every 30 s remain meaningful", max(late_rpm) > 0,
          f"after 150 s: {late_n} samples, max RPM={max(late_rpm)} (engine stays off); {len(meta.get('scenario_cycles', []))} fault cycles are still scheduled up to 600 s",
          rel(folder / "long-run.json"), notes="Duration is not exposed in the UI; reachable through the API/CLI. Faults scheduled after ~145 s have no effect on a parked vehicle.")
model = AnomalyModel()
w = next(r for r in analyzer.history if "features" in r)
xl = []
for _ in range(200):
    t = time.perf_counter()
    explain(model, w)
    xl.append((time.perf_counter() - t) * 1000)
perf2 = {"xai_ms_median": round(statistics.median(xl), 2), "xai_ms_p95": round(sorted(xl)[190], 2), "xai_ms_max": round(max(xl), 2)}
reg.check("QA-PERF-003", "XAI-001", "Repeated XAI explanations (200x) are fast and stable", "explain() on one window 200 times", "p95 < 500 ms (analysis cadence is 1 s)", perf2["xai_ms_p95"] < 500, json.dumps(perf2))
t = time.perf_counter()
for _ in range(5):
    AnomalyModel()
load_ms = (time.perf_counter() - t) / 5 * 1000
reg.check("QA-PERF-004", "AI-007", "Model load time", "AnomalyModel() x5", "< 2 s each", load_ms < 2000, f"{load_ms:.0f} ms per load")
# no explicit performance requirement exists in the project documents beyond non-blocking GUI and bounded queues
reg.add("QA-PERF-005", "NFR-001", "Project-defined performance limits", "search requirements for numeric limits", "tests against defined limits",
        "The control file defines no numeric latency/throughput requirements (only non-blocking GUI, bounded queue 32, 120 ms UI refresh); results above are measurements, not pass/fail against a spec",
        "PARTIAL", rel(folder / "long-run.json"))

# ---------------------------------------------------------------------------- GUI stress while data flows
gdb = tmp / "gui-stress.sqlite3"
for f in tmp.glob("gui-stress*"):
    f.unlink()
w = MainWindow(gdb)
w.show()
pump(until=lambda: w.backend_ready, limit=15)
modes = {w.mode_combo.itemData(i): i for i in range(w.mode_combo.count())}
fams = {w.family_combo.itemData(i): i for i in range(w.family_combo.count())}
w.family_combo.setCurrentIndex(fams["multisensor"])
w.mode_combo.setCurrentIndex(modes["RANDOM_FAULTS"])
for i in range(w.speed_combo.count()):
    if w.speed_combo.itemData(i) == 30:
        w.speed_combo.setCurrentIndex(i)
w.ai_enabled.setChecked(True)
ticks = []
timer = QTimer()
timer.timeout.connect(lambda: ticks.append(time.monotonic()))
timer.start(10)
mem_gui = [rss_mb()]
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
pump(until=lambda: not w.source_combo.isEnabled(), limit=10)
t_end = time.monotonic() + 25
reports_opened = pages = 0
errors = []
w.error_message = ""
while time.monotonic() < t_end:
    w.navigation.setCurrentRow(pages % 6)
    pages += 1
    if w.events_table.rowCount():
        row = (pages // 6) % w.events_table.rowCount()
        w.events_table.selectRow(row)
        item = w.events_table.item(row, 3)
        if item is not None and pages % 6 == 3:
            ev_id = w.event_rows[row]["event_id"] if row < len(w.event_rows) else None
            if ev_id:
                w.worker.submit("report", event_id=ev_id, language="ar")
                reports_opened += 1
    pump(0.15)
    if w.error_message and w.error_message not in errors:
        errors.append(w.error_message)
mem_gui.append(rss_mb())
QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton)
pump(until=lambda: w.source_combo.isEnabled(), limit=15)
gaps = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
p99 = sorted(gaps)[int(len(gaps) * 0.99)] if gaps else None
stress = {"page_switches": pages, "reports_requested": reports_opened, "event_rows": w.events_table.rowCount(), "max_gui_gap_s": round(max(gaps), 3) if gaps else None, "p99_gap_s": round(p99, 3) if p99 else None, "errors_shown": errors, "memory_mb": [round(m, 1) for m in mem_gui]}
(folder / "gui-stress.json").write_text(json.dumps(stress, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-PERF-006", "NFR-001", "GUI stays responsive while 30x RANDOM_FAULTS + AI run, pages are switched and reports opened", "25 s: switch pages every 150 ms, request reports",
          "no event-loop gap > 1 s; no error shown; reports produced", bool(gaps) and max(gaps) < 1.0 and not errors and w.events_table.rowCount() > 0, json.dumps(stress, ensure_ascii=False), rel(folder / "gui-stress.json"))

# ---------------------------------------------------------------------------- negative GUI cases
neg = {}
# double start while running
w.mode_combo.setCurrentIndex(modes["NORMAL"])
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
pump(until=lambda: not w.source_combo.isEnabled(), limit=10)
w.error_message = ""
w.start_source()  # programmatic second start (button is disabled for users)
pump(1.0)
neg["second_start_message"] = w.error_message or w.error_label.text()
neg["start_button_disabled_while_running"] = not w.start_button.isEnabled()
neg["source_locked"] = not w.source_combo.isEnabled()
# export failures during a running session must not be classified as connection loss
sess = None
import sqlite3  # noqa: E402

con = sqlite3.connect(f"file:{gdb}?mode=ro", uri=True)
sess = con.execute("select session_id from sessions order by started_at_ms desc limit 1").fetchone()[0]
before_count = con.execute("select count(*) from measurements").fetchone()[0]
for bad in (str(tmp / "no" / "such" / "dir" / "x.jsonl"), str(tmp)):
    w.error_message = ""
    w.worker.submit("export", session_id=sess, path=bad)
    pump(1.2)
    neg[f"export_to_{'missing_dir' if 'such' in bad else 'directory'}"] = (w.error_message or w.error_label.text())[:100]
pump(1.0)
after_count = con.execute("select count(*) from measurements").fetchone()[0]
conn_events = con.execute("select count(*) from events where kind='CONNECTION'").fetchone()[0]
neg["samples_still_flowing"] = after_count > before_count
neg["connection_events_created_by_export_errors"] = conn_events
neg["status_after_export_errors"] = w.status_label.text()
# language/theme change during a run
c0 = con.execute("select count(*) from measurements").fetchone()[0]
w.language_combo.setCurrentIndex(1)
w.theme_combo.setCurrentIndex(1)
pump(1.5)
c1 = con.execute("select count(*) from measurements").fetchone()[0]
neg["data_continues_after_language_theme_change"] = c1 > c0
# missing report
w.error_message = ""
w.worker.submit("report", event_id="does-not-exist", language="en")
pump(1.0)
neg["missing_report_text"] = w.report_text.toPlainText()[:60]
QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton)
pump(until=lambda: w.source_combo.isEnabled(), limit=15)
con.close()
timer.stop()
(folder / "negative-gui.json").write_text(json.dumps(neg, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-UI-020", "NFR-001", "Starting a second session while one is running is refused with a message", "call start_source() during a run", "message shown; first session unaffected",
          bool(neg["second_start_message"]) and neg["start_button_disabled_while_running"] and neg["source_locked"], json.dumps({k: neg[k] for k in ("second_start_message", "start_button_disabled_while_running", "source_locked")}, ensure_ascii=False), rel(folder / "negative-gui.json"))
reg.check("QA-UI-021", "FR-006/NFR-001", "Export to an unwritable path shows a local error and does NOT stop the source or create a CONNECTION event (old defect A06)",
          "export during a running session to a missing folder and to a directory", "error text, samples keep flowing, 0 CONNECTION events",
          neg["samples_still_flowing"] and neg["connection_events_created_by_export_errors"] == 0 and bool(neg["export_to_missing_dir"]) and bool(neg["export_to_directory"]),
          json.dumps({k: neg[k] for k in ("export_to_missing_dir", "export_to_directory", "samples_still_flowing", "connection_events_created_by_export_errors")}, ensure_ascii=False), rel(folder / "negative-gui.json"))
reg.check("QA-UI-022", "SETTINGS-001", "Changing language/theme during a session does not interrupt data", "toggle EN+dark during a run", "measurement count keeps increasing", neg["data_continues_after_language_theme_change"], "samples continued" if neg["data_continues_after_language_theme_change"] else "stalled")
reg.check("QA-UI-023", "UI-001", "Opening a report that does not exist shows a message and the window survives", "report for unknown id", "text 'not found' and window alive", w.isVisible() and bool(neg["missing_report_text"]), neg["missing_report_text"])
w.close()
pump(until=lambda: w.worker.isFinished(), limit=15)

# ---------------------------------------------------------------------------- negative data via replay files
good = tmp / "good.jsonl"
s = SimulationSource(seed=5, scenario_family="multisensor", mode="NORMAL", duration_ms=4000)
with SQLiteRepository(tmp / "mk.sqlite3") as repo:
    ss = Session(s, repo)
    ss.start()
    while not s.exhausted:
        ss.step()
    ss.stop()
    repo.export_session(ss.last_sample.session_id, good)
lines = good.read_text(encoding="utf8").splitlines()
rec = json.loads(lines[3])


def variant(name, mutate_line=None, raw=None, drop=None):
    ls = list(lines)
    if raw is not None:
        ls[3] = raw
    elif mutate_line:
        r_ = json.loads(ls[3])
        mutate_line(r_)
        ls[3] = json.dumps(r_)
    if drop:
        ls = [l for i, l in enumerate(ls) if i != drop]
    p = tmp / f"replay-{name}.jsonl"
    p.write_text("\n".join(ls) + "\n", encoding="utf8")
    try:
        res = ReplaySource(p).verify()
        return "ACCEPTED" if res.get("ok", True) else f"rejected: {str(res)[:80]}"
    except Exception as exc:  # noqa: BLE001
        return f"rejected: {type(exc).__name__}: {str(exc)[:70]}"


import re  # noqa: E402

rpm_match = re.search(r'"RPM":\{"quality":"AVAILABLE","unit":"rpm","value":([0-9.]+)\}', lines[3])
assert rpm_match, "RPM reading pattern not found in the exported replay line"


def with_rpm(token):
    return lines[3].replace(rpm_match.group(0), '"RPM":{"quality":"AVAILABLE","unit":"rpm","value":' + token + "}")


cases = {
    "valid": variant("valid"),
    "NaN value": variant("nan", raw=with_rpm("NaN")),
    "Infinity value": variant("inf", raw=with_rpm("Infinity")),
    "boolean value": variant("bool", lambda r: r["readings"]["RPM"].__setitem__("value", True)),
    "string value": variant("str", lambda r: r["readings"]["RPM"].__setitem__("value", "abc")),
    "missing field": variant("missing", lambda r: r.pop("timestamp_ms")),
    "backward timestamp": variant("back", lambda r: r.__setitem__("timestamp_ms", 0)),
    "duplicate sequence": variant("dupseq", lambda r: r.__setitem__("sequence_number", json.loads(lines[2])["sequence_number"])),
    "bad version": variant("ver", lambda r: r.__setitem__("sample_version", 9)),
    "bool version": variant("bver", lambda r: r.__setitem__("sample_version", True)),
    "corrupted line": variant("garbage", raw="{{{ corrupt"),
    "wrong unit": variant("unit", lambda r: r["readings"]["COOLANT_TEMP"].__setitem__("unit", "K")),
}
ok_valid = cases["valid"] == "ACCEPTED"
bad_all = all(v.startswith("rejected") for k, v in cases.items() if k != "valid")
(folder / "negative-data.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-SEC-001", "FR-004", "Invalid data in a replay file is rejected with an error (NaN, Infinity, bool, string, missing field, backward time, duplicate sequence, bad/bool version, corrupt line, wrong unit)",
          "11 mutated replay files + 1 valid", "valid accepted; every mutation rejected (no crash)", ok_valid and bad_all, json.dumps(cases, ensure_ascii=False)[:900], rel(folder / "negative-data.json"))


def session_probe(name, mutate):
    ls = list(lines)
    r_ = json.loads(ls[3])
    mutate(r_)
    ls[3] = json.dumps(r_)
    path = tmp / f"probe-{name}.jsonl"
    path.write_text("\n".join(ls) + "\n", encoding="utf8")
    dbp = tmp / f"probe-{name}.sqlite3"
    for f in tmp.glob(f"probe-{name}.sqlite3*"):
        f.unlink()
    with SQLiteRepository(dbp) as repo:
        src = ReplaySource(path)
        ss = Session(src, repo)
        ss.start()
        while not src.exhausted:
            ss.step()
        ss.stop()
        stored = json.loads(repo.connection.execute("select data_json from measurements where sequence_number=3").fetchone()[0])["readings"]
        kinds = [r["kind"] for r in repo.list_events()]
    return stored, kinds


stored, kinds = session_probe("huge", lambda r: r["readings"]["RPM"].__setitem__("value", 1e308))
reg.check("QA-SEC-002", "FR-004/DATA-001", "A finite but physically absurd reading (RPM = 1e308) in a REPLAY file is not stored as AVAILABLE",
          "replay file with RPM=1e308 through Session into SQLite", "flagged INVALID (or rejected) and a data-quality event",
          stored["RPM"]["quality"] != "AVAILABLE" or "DATA_QUALITY" in kinds,
          f"stored RPM value={stored['RPM']['value']} quality={stored['RPM']['quality']}; events={kinds}", rel(folder / "negative-data.json"),
          notes="Root cause: DEMO_BOUNDS are applied only when source/provenance is SIMULATION or DEVICE_TEST (monitoring/data_quality.py); REPLAY and other sources have no bound at all.")
stored, kinds = session_probe("foo", lambda r: r["readings"].__setitem__("FOO", {"value": 1, "unit": "x", "quality": "AVAILABLE"}))
reg.check("QA-SEC-003", "FR-004", "An unknown sensor id in a replay file is flagged (UNSUPPORTED + data-quality event), not silently accepted",
          "replay with sensor FOO", "quality UNSUPPORTED and DATA_QUALITY event", stored.get("FOO", {}).get("quality") == "UNSUPPORTED" and "DATA_QUALITY" in kinds,
          f"FOO stored={stored.get('FOO')}; events={kinds}", rel(folder / "negative-data.json"), notes="The value is still persisted (flagged), unlike the TCP/serial receiver which rejects unadvertised sensors.")
reg.save()
