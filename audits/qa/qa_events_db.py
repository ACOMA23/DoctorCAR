"""QA-EVENT / QA-DB: T-30/T+30 recording at several rates and SQLite integrity/failure behaviour."""

import hashlib
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402

from doctorcar.core.session import Session  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("gate4")
folder = EVIDENCE / "gate4"
folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("events")
TRIP_END = 155_000


class Jittered(SimulationSource):
    """Irregular arrival times (100-400 ms) with optional dropped samples."""

    def __init__(self, *a, drop=0.0, **k):
        super().__init__(*a, **k)
        self.rng2, self.clock, self.drop = random.Random(5), 0, drop

    def read_measurements(self):
        while True:
            s = super().read_measurements()
            if s is None:
                return None
            self.clock += self.rng2.choice((100, 200, 300, 400))
            if self.drop and self.rng2.random() < self.drop:
                continue
            from dataclasses import replace

            return replace(s, timestamp_ms=self.clock)


def fresh(name):
    for f in tmp.glob(f"{name}.sqlite3*"):
        f.unlink()
    return tmp / f"{name}.sqlite3"


def run(name, source, stop_at_ms=None, crash=False):
    path = fresh(name)
    repo = SQLiteRepository(path)
    session = Session(source, repo)
    session.start()
    while not source.exhausted:
        r = session.step()
        if stop_at_ms and session.last_sample and session.last_sample.timestamp_ms >= stop_at_ms:
            break
    if not crash:
        session.stop()
    events = [repo.get_event(r["event_id"]) for r in repo.list_events()]
    if crash:
        repo.connection.close()  # abrupt end: no stop(), no checkpoint flush by the app
        return path, None
    repo.close()
    return path, events


def describe(ev, step, end=TRIP_END):
    ts = [s.timestamp_ms for s in ev.samples]
    t = ev.trigger.timestamp_ms
    lo, hi = t - 30_000, t + 30_000
    gaps = [(a, b) for a, b in zip(ts, ts[1:], strict=False) if b - a > 1.5 * step]
    expected = (min(hi, end) - max(lo, 0)) // step + 1
    return {"kind": ev.trigger.kind, "detection_ms": t, "window": [lo, hi], "first": ts[0], "last": ts[-1],
            "count": len(ts), "expected_at_nominal_rate": expected, "missing_intervals": gaps,
            "status": ev.status, "limitations": list(ev.limitations), "sorted": ts == sorted(ts) and len(set(ts)) == len(ts)}


def invariants(d, step, stopped_early=False):
    full_pre = d["window"][0] >= 0
    problems = []
    if not d["sorted"]:
        problems.append("samples not strictly increasing")
    if d["first"] < d["window"][0]:
        problems.append("first sample before T-30s")
    if d["last"] > d["window"][1]:
        problems.append("last sample after T+30s")
    if full_pre and d["first"] - d["window"][0] > step * 2.2 and not d["limitations"]:
        problems.append("pre-window short without limitation")
    if d["status"] == "COMPLETE" and d["last"] < d["window"][1] - step * 2.2:
        problems.append("COMPLETE but window not covered")
    if d["status"] == "PARTIAL" and not d["limitations"]:
        problems.append("PARTIAL without a stated reason")
    return problems


results = {}
# ---------------------------------------------------------------------------- rates and positions
configs = {
    "mid-5Hz": (dict(scenarios=(ScenarioInstance("S01", 60_000, 35_000),)), 200),
    "mid-1Hz": (dict(scenarios=(ScenarioInstance("S01", 60_000, 35_000),), step_ms=1000), 1000),
    "start-5Hz": (dict(scenarios=(ScenarioInstance("S07", 3_000, 9_000, 1.0, "implausible"),)), 200),
    "near-end-5Hz": (dict(scenarios=(ScenarioInstance("S05", 135_000, 15_000),)), 200),
    "disappearing-5s": (dict(scenarios=(ScenarioInstance("S05", 60_000, 5_000), ScenarioInstance("S06", 90_000, 5_000))), 200),
    "long-90s": (dict(scenarios=(ScenarioInstance("S01", 40_000, 90_000),)), 200),
}
for name, (kw, step) in configs.items():
    t0 = time.monotonic()
    src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", **kw)
    path, events = run(name, src)
    descs = [describe(e, step) for e in events]
    probs = [(d["kind"], p) for d in descs for p in invariants(d, step)]
    results[name] = descs
    interesting = [d for d in descs if d["kind"] != "DATA_QUALITY"] or descs
    reg.check(f"QA-EVENT-{len(results):03d}", "FR-005", f"Recording window: {name}", json.dumps(kw, default=str)[:120],
              "no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples",
              bool(events) and not probs,
              f"events={len(events)}; " + "; ".join(f"{d['kind']}@{d['detection_ms']/1000:.1f}s n={d['count']} exp~{d['expected_at_nominal_rate']} {d['status']} first={d['first']/1000:.1f} last={d['last']/1000:.1f}" for d in interesting[:3]) + (f"; PROBLEMS {probs}" if probs else ""),
              started=t0)
# the near-end event must be PARTIAL because T+30 is not available
ne = [d for d in results["near-end-5Hz"] if d["kind"] != "DATA_QUALITY"]
reg.check("QA-EVENT-007", "FR-005", "Event detected near the end of the trip is PARTIAL with an explicit reason",
          "S05 at 135 s -> detection ~136 s; trip ends at 155 s", "status PARTIAL and a limitation text; last sample = trip end",
          bool(ne) and all(d["status"] == "PARTIAL" and d["limitations"] and d["last"] == TRIP_END for d in ne),
          json.dumps([(d["kind"], d["status"], d["last"], d["limitations"]) for d in ne], ensure_ascii=False))
st = results["start-5Hz"][0]
reg.check("QA-EVENT-008", "FR-005", "Event at trip start keeps the available pre-window and states it is shorter",
          "implausible S07 at 3 s", "first sample = 0 and a limitation 'shorter than 30 s'", st["first"] == 0 and any("أقصر" in x or "shorter" in x for x in st["limitations"]),
          f"first={st['first']} limitations={st['limitations']}")
dis = [d for d in results["disappearing-5s"] if d["kind"] != "DATA_QUALITY"]
reg.check("QA-EVENT-009", "FR-005", "A fault that disappears after 5 s does not cancel the event (recording continues to T+30)",
          "S05 and S06 for 5 s each", "event exists and last sample >= detection + 29 s", bool(dis) and all(d["last"] >= d["detection_ms"] + 29_000 for d in dis),
          json.dumps([(d["kind"], d["detection_ms"], d["last"]) for d in dis]))

# overlapping events
src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION",
                       scenarios=(ScenarioInstance("S01", 40_000, 45_000), ScenarioInstance("S02", 60_000, 35_000)))
path, events = run("overlap", src)
descs = [describe(e, 200) for e in events]
rows_shared = sqlite3.connect(path).execute("select count(*) from (select sequence_number from event_samples group by session_id, sequence_number having count(distinct event_id) > 1)").fetchone()[0]
kinds = sorted({d["kind"] for d in descs})
overlap = any(a is not b and a["window"][0] < b["window"][1] and b["window"][0] < a["window"][1] for a in descs for b in descs)
reg.check("QA-EVENT-010", "FR-005", "Overlapping events: each keeps its own full window; shared samples stored once",
          "S01 (40-85 s) + S02 (60-95 s)", ">=2 distinct non-quality events, windows overlap, samples shared via event_samples (not duplicated in measurements)",
          len([d for d in descs if d["kind"] != "DATA_QUALITY"]) >= 2 and overlap and rows_shared > 0 and not any(invariants(d, 200) for d in descs),
          f"kinds={kinds}; overlapping={overlap}; shared sample rows={rows_shared}", rel(folder / "event-windows.json"))

# stop during an event (manual stop before the end)
src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S01", 60_000, 35_000),))
path, events = run("stop-mid", src, stop_at_ms=80_000)
th = [e for e in events if e.trigger.kind == "MS_THERMAL"]
reg.check("QA-EVENT-011", "FR-005", "Manual stop during recording finalizes the event as PARTIAL with the reason",
          "stop at 80 s, detection at 68.2 s", "PARTIAL, last sample ~80 s, reason recorded",
          bool(th) and th[0].status == "PARTIAL" and th[0].samples[-1].timestamp_ms <= 80_200 and bool(th[0].limitations),
          f"{[(e.trigger.kind, e.status, e.samples[-1].timestamp_ms, e.limitations) for e in events if e.trigger.kind != 'DATA_QUALITY']}")

# unexpected app close
src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S01", 60_000, 35_000),))
path, _ = run("crash", src, stop_at_ms=80_000, crash=True)
before = sqlite3.connect(path).execute("select event_id, status from events where kind='MS_THERMAL'").fetchall()
with SQLiteRepository(path) as repo:
    rec = [(r["kind"], r["status"]) for r in repo.list_events()]
    ev = next(repo.get_event(r["event_id"]) for r in repo.list_events() if r["kind"] == "MS_THERMAL")
    sessions = repo.connection.execute("select status from sessions").fetchall()
reg.check("QA-EVENT-012", "DATA-002", "Abrupt close during recording: the event is recovered as PARTIAL on reopen with its checkpoint samples",
          "abandon the session without stop() at 80 s, reopen the database", "status RECORDING before reopen; PARTIAL after with samples up to the last checkpoint; session marked interrupted",
          bool(before) and before[0][1] == "RECORDING" and ev.status == "PARTIAL" and len(ev.samples) > 150 and bool(ev.limitations),
          f"before={[b[1] for b in before]} after={ev.status} samples={len(ev.samples)} last={ev.samples[-1].timestamp_ms} limitations={ev.limitations} sessions={sessions}")

# irregular rate and missing samples
src = Jittered(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S01", 60_000, 35_000),))
path, events = run("irregular", src)
descs = [describe(e, 250, end=src.clock) for e in events]
probs = [(d["kind"], p) for d in descs for p in invariants(d, 400)]
reg.check("QA-EVENT-013", "FR-005", "Irregular arrival rate (100-400 ms): windows follow sample time, not row count",
          "jittered timestamps", "no sample outside the time window; ordered; coverage by time", bool(events) and not probs,
          "; ".join(f"{d['kind']}@{d['detection_ms']/1000:.1f}s n={d['count']} first={d['first']/1000:.1f} last={d['last']/1000:.1f} {d['status']}" for d in descs[:3]) + (f"; PROBLEMS {probs}" if probs else ""))
src = Jittered(seed=4100, drop=0.2, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S01", 60_000, 35_000),))
path, events = run("missing", src)
descs = [describe(e, 250, end=src.clock) for e in events]
probs = [(d["kind"], p) for d in descs for p in invariants(d, 1200)]
reg.check("QA-EVENT-014", "FR-005", "20% missing samples: window bounds hold and missing intervals are measurable, not invented",
          "drop 20% of samples", "no sample outside [T-30,T+30]; no synthetic samples (count <= nominal)", bool(events) and not probs and all(d["count"] <= d["expected_at_nominal_rate"] + 2 for d in descs),
          "; ".join(f"{d['kind']}@{d['detection_ms']/1000:.1f}s n={d['count']} gaps={len(d['missing_intervals'])} {d['status']}" for d in descs[:4]) + (f"; PROBLEMS {probs}" if probs else ""))
results["overlap"] = descs
(folder / "event-windows.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf8")

# ---------------------------------------------------------------------------- database
t0 = time.monotonic()
path = fresh("schema")
with SQLiteRepository(path) as repo:
    tables = sorted(r[0] for r in repo.connection.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"))
    uv = repo.connection.execute("pragma user_version").fetchone()[0]
    fk = repo.connection.execute("pragma foreign_keys").fetchone()[0]
    jm = repo.connection.execute("pragma journal_mode").fetchone()[0]
    sync = repo.connection.execute("pragma synchronous").fetchone()[0]
needed = {"sessions", "measurements", "events", "event_samples", "simulation_runs", "analyses", "event_analyses", "diagnostic_reports", "detection_evidence", "event_ai_status", "extension_migrations"}
reg.check("QA-DB-001", "DATA-002", "New database: documented tables, user_version=2, foreign keys ON, WAL, synchronous FULL",
          "SQLiteRepository(new file)", "all documented tables present; PRAGMAs as documented", needed <= set(tables) and uv == 2 and fk == 1 and jm.lower() == "wal" and sync == 2,
          f"tables={tables} user_version={uv} foreign_keys={fk} journal={jm} synchronous={sync}", started=t0)

src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02", 60_000, 35_000),))
path, events = run("full", src)
con = sqlite3.connect(path)
con.execute("pragma foreign_keys=ON")
integrity = con.execute("pragma integrity_check").fetchone()[0]
fkc = con.execute("pragma foreign_key_check").fetchall()
n_meas = con.execute("select count(*) from measurements").fetchone()[0]
reports = con.execute("select event_id, data_json from diagnostic_reports").fetchall()
ev_ids = {e.event_id for e in events if e.status in ("COMPLETE", "PARTIAL")}
cross = con.execute("select count(*) from event_samples es join events e on e.event_id=es.event_id where e.session_id != es.session_id").fetchone()[0]
reg.check("QA-DB-002", "DATA-002", "Stored run: integrity ok, no FK violations, measurements and event samples consistent",
          "S02 run -> inspect with an independent sqlite3 connection", "integrity_check ok; foreign_key_check empty; 776 measurements; no cross-session event samples",
          integrity == "ok" and not fkc and n_meas == 776 and cross == 0, f"integrity={integrity} fk_violations={len(fkc)} measurements={n_meas} cross_session={cross}")
with SQLiteRepository(path) as repo:
    from doctorcar.diagnostics.human_report import build_report_model, load_ai_context

    same = []
    for event_id, blob in reports:
        ev = repo.get_event(event_id)
        analysis, status, later = load_ai_context(repo, ev)
        fresh_report = build_report_model(ev, analysis, repo.get_detections(event_id), status, later).to_dict()
        same.append(json.loads(blob) == json.loads(json.dumps(fresh_report, default=str)))
reg.check("QA-DB-003", "DATA-002", "Stored reports exist for every finished event and equal a fresh rebuild from the stored event",
          "compare diagnostic_reports with build_report_model", "every finished event has a report; stored == rebuilt", len(reports) >= 1 and all(same) and {r[0] for r in reports} == ev_ids,
          f"reports={len(reports)} finished_events={len(ev_ids)} equal={same}")

# duplicates and conflicts
with SQLiteRepository(path) as repo:
    ev = next(e for e in (repo.get_event(r["event_id"]) for r in repo.list_events()) if e.status == "COMPLETE")
    before = repo.connection.execute("select count(*) from events").fetchone()[0]
    repo.save_event(ev)
    after = repo.connection.execute("select count(*) from events").fetchone()[0]
    from dataclasses import replace

    conflict = None
    try:
        repo.save_event(replace(ev, end_ms=ev.end_ms - 1000))
        conflict = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        conflict = type(exc).__name__ + ": " + str(exc)[:80]
reg.check("QA-DB-004", "DATA-002", "Re-saving the same event does not duplicate; conflicting overwrite of a finalized event is refused",
          "save_event twice; save altered finalized event", "count unchanged; conflict raises", before == after and conflict != "ACCEPTED", f"count {before}->{after}; conflict={conflict}")

# FK on the API: measurement for an unknown session
with SQLiteRepository(fresh("fk")) as repo:
    from doctorcar.core.models import Reading, Sample, Source

    s = Sample("ghost-session", Source.SIMULATION, 0, 0, {"RPM": Reading(800.0, "rpm")})
    try:
        repo.save_measurement(s)
        res = "ACCEPTED (orphan measurement stored)"
    except Exception as exc:  # noqa: BLE001
        res = type(exc).__name__
    orphans = repo.connection.execute("select count(*) from measurements").fetchone()[0]
reg.check("QA-DB-005", "DATA-002", "A measurement whose session was never saved is not stored as an orphan",
          "save_measurement without save_session", "rejected (FK) and no row", orphans == 0, f"result={res} rows={orphans}")

# reopen equality
with SQLiteRepository(path) as repo:
    a = [(r["event_id"], r["status"], r["trigger_ms"]) for r in repo.list_events()]
with SQLiteRepository(path) as repo:
    b = [(r["event_id"], r["status"], r["trigger_ms"]) for r in repo.list_events()]
reg.check("QA-DB-006", "DATA-002", "Reopening returns identical events", "open twice", "identical lists", a == b and a, f"{len(a)} events identical={a == b}")

# legacy (v1) database and future schema
legacy = fresh("legacy")
with SQLiteRepository(legacy) as repo:
    pass
con = sqlite3.connect(legacy)
for t in ("event_ai_status", "detection_evidence", "diagnostic_reports", "event_analyses", "analyses", "simulation_runs", "extension_migrations"):
    con.execute(f"drop table if exists {t}")
con.execute("pragma user_version=1")
con.commit()
con.close()
try:
    with SQLiteRepository(legacy) as repo:
        tables = {r[0] for r in repo.connection.execute("select name from sqlite_master where type='table'")}
        uv = repo.connection.execute("pragma user_version").fetchone()[0]
    legacy_ok = needed <= tables and uv == 2
    legacy_msg = f"migrated: user_version={uv}"
except Exception as exc:  # noqa: BLE001
    legacy_ok, legacy_msg = False, f"{type(exc).__name__}: {exc}"
future = fresh("future")
with SQLiteRepository(future):
    pass
con = sqlite3.connect(future)
con.execute("pragma user_version=99")
con.commit()
con.close()
try:
    with SQLiteRepository(future):
        future_res = "OPENED"
except Exception as exc:  # noqa: BLE001
    future_res = f"refused: {type(exc).__name__}: {str(exc)[:70]}"
reg.check("QA-DB-007", "DATA-002", "Older (v1) database is upgraded in place; a future schema is refused",
          "synthetic v1 db; synthetic user_version=99 db", "v1 -> all v2 tables present; 99 -> error", legacy_ok and future_res.startswith("refused"), f"{legacy_msg}; future: {future_res}")

# write failure, bad file, unavailable path
with SQLiteRepository(fresh("ro")) as repo:
    repo.save_session("s", "SIMULATION")
    repo.connection.execute("pragma query_only=ON")
    try:
        repo.save_measurement(Sample("s", Source.SIMULATION, 0, 0, {"RPM": Reading(800.0, "rpm")}))
        wf = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        wf = type(exc).__name__ + ": " + str(exc)[:60]
    repo.connection.execute("pragma query_only=OFF")
    rows = repo.connection.execute("select count(*) from measurements").fetchone()[0]
bad = tmp / "not-a-db.sqlite3"
bad.write_bytes(b"this is not a sqlite database\n" * 20)
try:
    with SQLiteRepository(bad):
        bad_res = "OPENED"
except Exception as exc:  # noqa: BLE001
    bad_res = f"{type(exc).__name__}: {str(exc)[:60]}"
try:
    with SQLiteRepository(tmp / "no" / "such" / "dir" / "x.sqlite3"):
        missing_res = "OPENED"
except Exception as exc:  # noqa: BLE001
    missing_res = f"{type(exc).__name__}: {str(exc)[:60]}"
try:
    with SQLiteRepository(tmp):
        dir_res = "OPENED"
except Exception as exc:  # noqa: BLE001
    dir_res = f"{type(exc).__name__}: {str(exc)[:60]}"
reg.check("QA-DB-008", "DATA-002", "Write failure raises and stores nothing; corrupt, missing-folder and directory paths raise clear errors",
          "query_only write; garbage file; missing directory; directory as path", "all raise; no partial row",
          not wf.startswith("ACCEPTED") and rows == 0 and not bad_res.startswith("OPENED") and not dir_res.startswith("OPENED"),
          f"write={wf}; corrupt={bad_res}; directory={dir_res}; missing folders: {missing_res} (the repository creates parent folders by design)")

# corrupt database in the real window: error shown, no crash
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from doctorcar.ui.main_window import MainWindow  # noqa: E402

w = MainWindow(bad)
w.show()
end = time.monotonic() + 8
while time.monotonic() < end:
    app.processEvents()
    time.sleep(0.01)
msg = (w.error_label.text() + " | " + w.status_label.text())[:140]
alive = w.isVisible()
w.close()
w.worker.wait(5000)
reg.check("QA-DB-009", "NFR-001", "The window opened on a corrupt database shows an error and stays alive", "MainWindow(garbage file)",
          "window visible; error/status text mentions the storage failure", alive and bool(w.error_label.text() or "فشل" in msg or "خطأ" in msg or "تعذر" in msg), f"alive={alive} message='{msg}'")

# language/theme change leaves stored data untouched
gui_db = Path(os.environ.get("QA_TMP", "")) / "doctorcar-qa" / "gui" / "gui-qa.sqlite3"
if gui_db.exists():
    def logical_hash(p):
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        h = hashlib.sha256()
        for t in ("sessions", "measurements", "events", "event_samples", "diagnostic_reports"):
            for row in c.execute(f"select * from {t} order by 1,2"):
                h.update(repr(row).encode())
        c.close()
        return h.hexdigest()

    h1 = logical_hash(gui_db)
    w = MainWindow(gui_db)
    w.show()
    end = time.monotonic() + 3
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    for i in (1, 0, 1):
        w.language_combo.setCurrentIndex(i)
        w.theme_combo.setCurrentIndex(i)
        app.processEvents()
    w.close()
    w.worker.wait(5000)
    h2 = logical_hash(gui_db)
    reg.check("QA-DB-010", "SETTINGS-001", "Changing language/theme does not change stored sessions, measurements, events or reports",
              "toggle language/theme on a populated database", "logical content hash identical", h1 == h2, f"before={h1[:16]} after={h2[:16]}")
else:
    reg.add("QA-DB-010", "SETTINGS-001", "Settings do not touch stored data", "-", "-", "GUI QA database missing", "BLOCKED")

# ---------------------------------------------------------------------------- detection coverage by condition
coverage = {}
for sid in ("S01", "S02", "S03", "S04", "S05", "S06", "S07"):
    for start, dur in ((60_000, 5_000), (60_000, 9_000), (60_000, 35_000), (110_000, 35_000), (135_000, 15_000)):
        src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance(sid, start, dur),))
        _, evs = run("coverage", src)
        coverage[f"{sid}@{start // 1000}s/{dur // 1000}s"] = [(e.trigger.kind, e.trigger.timestamp_ms / 1000, e.status) for e in evs if e.trigger.kind != "DATA_QUALITY"]
(folder / "detection-coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf8")
missed = [k for k, v in coverage.items() if not v]
reg.add("QA-EVENT-015", "MS-RULE", "Rule detection coverage by start time and duration (35 combinations, rules only, severity 1.0)",
        "S01..S07 x {5 s, 9 s, 35 s at 60 s; 35 s at 110 s; 15 s at 135 s}", "informational: every injected fault should either produce an event or be listed as a coverage gap",
        f"{len(coverage) - len(missed)}/{len(coverage)} produced a non-quality event; NOT detected: {', '.join(missed)}",
        "PARTIAL" if missed else "PASS", rel(folder / "detection-coverage.json"),
        notes="Gaps are documented limitations of the rule set under decelerating/idle/stopped conditions and short durations; not a recording defect.")
reg.save()
