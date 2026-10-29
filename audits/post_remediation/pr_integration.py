"""DC-VERIFY-002 integration regression (product code only called, never changed).

Covers: normal / long / fault / multi-fault / random simulation, T+30 repeat event, T-30/T+30 storage and
restoration, implausible Replay readings, rules vs advisory ML, SQLite integrity. Uses only temp databases.
"""

import json
import math
import os
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qa"))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402

from doctorcar.analysis.analyzer import AnomalyAnalyzer  # noqa: E402
from doctorcar.core.models import Quality  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.monitoring.data_quality import PHYSICAL_BOUNDS  # noqa: E402
from doctorcar.sources.replay import ReplaySource  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("integration")
folder = EVIDENCE / "integration"
folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("pr-int")
EXPECTED = {"S01": "MS_THERMAL", "S02": "MS_AIR_FUEL", "S03": "MS_FUEL_RESPONSE", "S04": "MS_AIRFLOW",
            "S05": "MS_SUPPLY", "S06": "MS_COMBUSTION", "S07": "MS_SIGNAL"}
SENSORS = ["RPM", "SPEED", "COOLANT_TEMP", "ENGINE_LOAD", "THROTTLE_POS", "INTAKE_PRESSURE", "MAF",
           "INTAKE_TEMP", "SHORT_FUEL_TRIM", "LONG_FUEL_TRIM", "CONTROL_MODULE_VOLTAGE"]
dbs: list[Path] = []


def fresh(name):
    for f in tmp.glob(f"{name}.sqlite3*"):
        f.unlink()
    p = tmp / f"{name}.sqlite3"
    dbs.append(p)
    return p


def run(name, source, analyzer=None, ml_alerts=True, stop_after_ms=None):
    path = fresh(name)
    with SQLiteRepository(path) as repo:
        session = Session(source, repo, analyzer=analyzer, ml_alerts=ml_alerts)
        session.start()
        n = 0
        while not source.exhausted:
            session.step()
            n += 1
            if stop_after_ms and session.last_sample and session.last_sample.timestamp_ms >= stop_after_ms:
                break
        session.stop()
        sid = source.session_id
        rows = [dict(r) for r in repo.list_events()]
        evs = [repo.get_event(r["event_id"]) for r in rows]
    return path, sid, rows, evs, session


def sim(seed=4100, scen=(), **kw):
    mode = "FAULT_INJECTION" if scen else kw.pop("mode", "NORMAL")
    return SimulationSource(seed=seed, scenario_family="multisensor", mode=mode, scenarios=tuple(scen), **kw)


def measurements(path, sid):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [json.loads(r[0]) for r in con.execute(
            "SELECT data_json FROM measurements WHERE session_id=? ORDER BY timestamp_ms", (sid,))]
    finally:
        con.close()


def rule_events(rows):
    return [(r["kind"], r["trigger_ms"] / 1000) for r in rows if r["kind"] != "DATA_QUALITY"]


# ------------------------------------------------------------------ INT-001 normal trips
t0 = time.monotonic()
res, bad = {}, []
for seed in (42, 777, 2026, 4100, 8001, 8002):
    path, sid, rows, evs, _ = run(f"n{seed}", sim(seed))
    ms = measurements(path, sid)
    ts = [m["timestamp_ms"] for m in ms]
    avail = all(all(m["readings"].get(k, {}).get("quality") == "AVAILABLE" for k in SENSORS) for m in ms)
    inb = all(PHYSICAL_BOUNDS[k][0] <= m["readings"][k]["value"] <= PHYSICAL_BOUNDS[k][1] for m in ms for k in SENSORS)
    mono = all(b - a == 200 for a, b in zip(ts, ts[1:], strict=False))
    res[seed] = {"samples": len(ms), "events": rule_events(rows), "all_available": avail, "in_bounds": inb, "step_200ms": mono}
    if not (len(ms) == 776 and not rule_events(rows) and avail and inb and mono):
        bad.append(seed)
(folder / "normal-trips.json").write_text(json.dumps(res, indent=2), encoding="utf8")
reg.check("QA-REG-001", "SIM-001", "Natural trips (6 seeds): 776 samples, 11 sensors AVAILABLE and physically plausible, 0 rule events, 200 ms axis",
          "SimulationSource NORMAL default length through Session + SQLite", "all 6 seeds clean", not bad, json.dumps({k: (v['samples'], len(v['events'])) for k, v in res.items()}),
          rel(folder / "normal-trips.json"), started=t0)

# ------------------------------------------------------------------ INT-002 sensor values update, per sensor
path, sid, rows, evs, _ = run("n_vals", sim(4100))
ms = measurements(path, sid)
distinct = {k: len({round(m["readings"][k]["value"], 3) for m in ms}) for k in SENSORS}
rng = {k: (min(m["readings"][k]["value"] for m in ms), max(m["readings"][k]["value"] for m in ms)) for k in SENSORS}
(folder / "sensor-values.json").write_text(json.dumps({"distinct_values": distinct, "min_max": rng}, indent=2), encoding="utf8")
reg.check("QA-REG-002", "SIM-001", "Every sensor changes over the trip (stored readings come from the simulator, not constants)",
          "count distinct stored values per sensor over 776 samples", ">= 5 distinct values for every sensor except possibly trims", all(v >= 5 for k, v in distinct.items()),
          json.dumps(distinct), rel(folder / "sensor-values.json"))

# ------------------------------------------------------------------ INT-003 long runs
t0 = time.monotonic()
long_res = {}
for seed, dur in ((42, 600_000), (2026, 900_000)):
    path, sid, rows, evs, _ = run(f"long{dur}", sim(seed, duration_ms=dur))
    ms = measurements(path, sid)
    ts = [m["timestamp_ms"] for m in ms]
    after = [m["readings"]["RPM"]["value"] for m in ms if m["timestamp_ms"] >= 45_000]
    wrapped = [m["readings"]["SPEED"]["value"] for m in ms if m["timestamp_ms"] >= 150_000]
    long_res[dur] = {"samples": len(ms), "expected": dur // 200 + 1, "contiguous": all(b - a == 200 for a, b in zip(ts, ts[1:], strict=False)),
                     "min_rpm_after_45s": min(after), "max_speed_after_150s": max(wrapped), "min_speed_after_150s": min(wrapped),
                     "rule_events": rule_events(rows)}
(folder / "long-sim.json").write_text(json.dumps(long_res, indent=2), encoding="utf8")
ok = all(v["samples"] == v["expected"] and v["contiguous"] and v["min_rpm_after_45s"] > 500 and v["max_speed_after_150s"] > 20 and not v["rule_events"] for v in long_res.values())
reg.check("QA-REG-003", "SIM-004 (DEF-006)", "Long simulation (600 s and 900 s) keeps driving: no engine stop, continuous time axis, no false events",
          "duration_ms 600000 / 900000 through Session", "3001/4501 samples, RPM > 500 after 45 s, speed still varies after 150 s, 0 events", ok, json.dumps(long_res), rel(folder / "long-sim.json"), started=t0)
path, sid, rows, evs, _ = run("dflt", sim(4100))
reg.check("QA-REG-004", "SIM-004", "Default 155 s trip unchanged by the long-run fix (776 samples ending at 155.0 s)",
          "default duration", "776 samples, last timestamp 155000", len(measurements(path, sid)) == 776 and measurements(path, sid)[-1]["timestamp_ms"] == 155000, "776 samples; last=155000")

# ------------------------------------------------------------------ INT-004 single faults
t0 = time.monotonic()
single, bad = {}, []
for sid_, kind in EXPECTED.items():
    path, sid, rows, evs, _ = run(f"s_{sid_}", sim(4100, (ScenarioInstance(sid_, 60_000, 35_000),)))
    ev = rule_events(rows)
    single[sid_] = ev
    if kind not in [k for k, _ in ev]:
        bad.append(sid_)
(folder / "single-faults.json").write_text(json.dumps(single, indent=2), encoding="utf8")
reg.check("QA-REG-005", "SIM-002", "Seven single faults (60 s, 35 s) each raise their own rule event", "S01..S07 FAULT_INJECTION", "each expected MS_* kind present",
          not bad, "; ".join(f"{k}->{[e[0] for e in v]}" for k, v in single.items()), rel(folder / "single-faults.json"), started=t0)

# ------------------------------------------------------------------ INT-005 multi faults
t0 = time.monotonic()
combos = [("S04", "S07"), ("S01", "S05"), ("S02", "S06"), ("S03", "S05"), ("S01", "S07"), ("S02", "S07")]
multi, bad = {}, []
for a, b in combos:
    try:
        path, sid, rows, evs, _ = run(f"m_{a}{b}", sim(4100, (ScenarioInstance(a, 60_000, 35_000), ScenarioInstance(b, 60_000, 35_000))))
        kinds = {k for k, _ in rule_events(rows)}
        multi[f"{a}+{b}"] = sorted(kinds)
        if not {EXPECTED[a], EXPECTED[b]} <= kinds:
            bad.append(f"{a}+{b}:{sorted(kinds)}")
    except ValueError as exc:
        multi[f"{a}+{b}"] = f"not injectable: {exc}"
(folder / "multi-faults.json").write_text(json.dumps(multi, indent=2, ensure_ascii=False), encoding="utf8")
reg.check("QA-REG-006", "SIM-002 (DEF-004)", "Simultaneous faults keep every event (S04+S07 included)", "six pairs injected at 60 s for 35 s",
          "both expected kinds for every injectable pair (masking fixed); non-injectable pairs reported", not bad, json.dumps(multi, ensure_ascii=False), rel(folder / "multi-faults.json"), started=t0,
          notes="Pairs rejected by the simulator are not counted as failures; they conflict on the sensors they write (documented in DC-FIX-001).")

# ------------------------------------------------------------------ INT-006 random faults
t0 = time.monotonic()
rnd, bad = {}, []
for seed in range(300, 312):
    try:
        path, sid, rows, evs, _ = run(f"r{seed}", sim(seed, mode="RANDOM_FAULTS", max_faults=3))
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        n_inj = con.execute("SELECT count(*) FROM simulation_runs").fetchone()[0]
        con.close()
        rnd[seed] = {"rule_events": rule_events(rows), "all_complete": all(r["status"] == ("COMPLETE" if r["trigger_ms"] + 30_000 <= 155_000 else "PARTIAL") for r in rows), "simulation_runs_rows": n_inj}
        if not rnd[seed]["all_complete"]:
            bad.append(seed)
    except Exception as exc:  # noqa: BLE001
        rnd[seed] = {"crash": repr(exc)}
        bad.append(seed)
(folder / "random-faults.json").write_text(json.dumps(rnd, indent=2), encoding="utf8")
reg.check("QA-REG-007", "SIM-003", "Random multisensor faults (12 seeds): runs finish, events complete, no crash", "RANDOM_FAULTS max 3",
          "no exception; event COMPLETE if T+30 s fits in the 155 s trip, otherwise PARTIAL (trip ended)", not bad, f"seeds={len(rnd)} with_events={sum(1 for v in rnd.values() if v.get('rule_events'))} bad={bad}", rel(folder / "random-faults.json"), started=t0)

# ------------------------------------------------------------------ INT-007 repeated event at T+30 exactly
first_start = 60_000
path, sid, rows, evs, _ = run("t30a", sim(4100, (ScenarioInstance("S02", first_start, 9_000),)))
t1 = [r["trigger_ms"] for r in rows if r["kind"] == "MS_AIR_FUEL"]
if t1:
    second = first_start + 30_000
    path, sid, rows, evs, _ = run("t30b", sim(4100, (ScenarioInstance("S02", first_start, 9_000), ScenarioInstance("S02", second, 9_000))))
    air = sorted(r["trigger_ms"] for r in rows if r["kind"] == "MS_AIR_FUEL")
    gap = (air[1] - air[0]) if len(air) > 1 else None
    reg.check("QA-REG-008", "FR-005 (DEF-005)", "A second fault of the same kind whose trigger lands exactly at T+30 is recorded, not swallowed",
              "S02 at 60 s (9 s) and S02 at 90 s (9 s): the second trigger is the first + 30.0 s", "two MS_AIR_FUEL events 30.0 s apart, both COMPLETE",
              len(air) == 2 and gap == 30_000 and all(r["status"] == "COMPLETE" for r in rows),
              f"first-run triggers={t1}; two-fault triggers={air}; gap={gap}; statuses={[r['status'] for r in rows]}")
else:
    reg.add("QA-REG-008", "FR-005", "T+30 repeat", "S02 9 s", "event", "first run produced no MS_AIR_FUEL, repeat not constructible", "BLOCKED")

# ------------------------------------------------------------------ INT-008 T-30 / T+30 storage and restoration
t0 = time.monotonic()
path, sid, rows, evs, _ = run("win", sim(4100, (ScenarioInstance("S01", 60_000, 35_000),)))
chk = []
for ev in evs:
    ts = [s.timestamp_ms for s in ev.samples]
    T = ev.trigger.timestamp_ms
    chk.append({"kind": ev.trigger.kind, "T_s": T / 1000, "first_s": ts[0] / 1000, "last_s": ts[-1] / 1000, "n": len(ts), "status": ev.status,
                "pre_ok": ts[0] <= T - 29_800 or ts[0] == 0, "post_ok": ts[-1] >= T + 29_800 or ts[-1] >= 154_800, "ordered": ts == sorted(ts)})
with SQLiteRepository(path) as again:  # a brand new connection = restoration after "restart"
    restored = [again.get_event(r["event_id"]) for r in again.list_events()]
same = all([s.to_dict() for s in a.samples] == [s.to_dict() for s in b.samples] and a.trigger == b.trigger for a, b in zip(evs, restored, strict=True))
exp = folder / "restored-session.jsonl"
with SQLiteRepository(path) as r2:
    r2.export_session(sid, exp)
rp = ReplaySource(exp)
info = rp.verify()
(folder / "event-windows.json").write_text(json.dumps(chk, indent=2), encoding="utf8")
reg.check("QA-REG-009", "FR-005", "Event window holds T-30..T+30, saved to SQLite, restored identically by a new connection; export verifies as Replay",
          "S01 at 60 s -> events -> reopen DB -> export -> ReplaySource.verify", "pre/post coverage, ordered, restored == saved, export 776 samples",
          bool(chk) and all(c["pre_ok"] and c["post_ok"] and c["ordered"] and c["status"] == "COMPLETE" for c in chk if c["kind"] != "DATA_QUALITY") and same and info["samples"] == 776,
          json.dumps(chk) + f"; restored_identical={same}; replay_verify={info}", rel(folder / "event-windows.json"), started=t0)

# ------------------------------------------------------------------ INT-009 implausible Replay readings
t0 = time.monotonic()
lines = [json.loads(x) for x in exp.read_text("utf8").splitlines()]
finite_bad = {100: ("RPM", 1e308), 101: ("RPM", -5000.0), 102: ("RPM", 9_999_999.0), 120: ("COOLANT_TEMP", 500.0), 130: ("MAF", 1e9), 140: ("INTAKE_PRESSURE", 5000.0)}
mut = folder / "replay-implausible-finite.jsonl"
with mut.open("w", encoding="utf8") as fh:
    for i, d in enumerate(lines):
        if i in finite_bad:
            k, v = finite_bad[i]
            d["readings"][k]["value"] = v
        fh.write(json.dumps(d) + "\n")
outcome = {}
try:
    outcome["verify"] = ReplaySource(mut).verify()
except Exception as exc:  # noqa: BLE001
    outcome["verify"] = f"{type(exc).__name__}: {str(exc)[:160]}"
try:
    path2, sid2, rows2, evs2, _ = run("impl", ReplaySource(mut))
    ms2 = measurements(path2, sid2)
    by_t = {m["timestamp_ms"]: m for m in ms2}
    bad_avail, shown = [], {}
    for m in ms2:
        for k, rd in m["readings"].items():
            v = rd.get("value")
            if rd.get("quality") == "AVAILABLE" and isinstance(v, (int, float)) and k in PHYSICAL_BOUNDS and not (PHYSICAL_BOUNDS[k][0] <= v <= PHYSICAL_BOUNDS[k][1]):
                bad_avail.append((m["timestamp_ms"], k, v))
    for i, (k, v) in finite_bad.items():
        m = by_t.get(i * 200)
        shown[f"{k}={v:g}@{i * 0.2:.1f}s"] = (m["readings"][k]["quality"], m["readings"][k]["value"]) if m else "sample not stored"
    outcome.update({"run": "completed", "stored": len(ms2), "implausible_stored_as_AVAILABLE": bad_avail, "injected_readings_state": shown,
                    "events": [(r["kind"], r["trigger_ms"] / 1000) for r in rows2]})
    survived = not bad_avail and all(isinstance(v, (list, tuple)) and v[0] != "AVAILABLE" for v in shown.values())
except Exception as exc:  # noqa: BLE001
    outcome.update({"run": f"{type(exc).__name__}: {str(exc)[:160]}"})
    survived = False
(folder / "replay-implausible-finite.json").write_text(json.dumps(outcome, indent=2, default=str), encoding="utf8")
reg.check("QA-REG-010", "DATA (DEF-007)", "Replay with finite implausible values (RPM=1e308/-5000/9999999, 500 C, MAF 1e9, 5000 kPa): never AVAILABLE, session survives",
          "mutate 6 samples of an exported session and replay it through Session", "each injected reading stored with a non-AVAILABLE quality", survived, json.dumps(outcome, default=str)[:700],
          rel(folder / "replay-implausible-finite.json"), started=t0)
nonfinite = {}
for token in ("NaN", "Infinity", "-Infinity"):
    f = folder / f"replay-{token.replace('-', 'neg')}.jsonl"
    with f.open("w", encoding="utf8") as fh:
        for i, d in enumerate(lines):
            raw = json.dumps(d)
            if i == 100:
                raw = raw.replace(json.dumps(d["readings"]["RPM"]["value"]), token, 1)
            fh.write(raw + "\n")
    try:
        ReplaySource(f).verify()
        nonfinite[token] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        nonfinite[token] = f"rejected: {type(exc).__name__}: {str(exc)[:90]}"
(folder / "replay-nonfinite.json").write_text(json.dumps(nonfinite, indent=2), encoding="utf8")
reg.check("QA-REG-010b", "DATA (DEF-007)", "Replay containing NaN / Infinity / -Infinity as a reading value is rejected with a clear error, not stored", "three crafted files, ReplaySource.verify",
          "all rejected by validation (ValueError)", all(v.startswith("rejected: ValueError") for v in nonfinite.values()), json.dumps(nonfinite), rel(folder / "replay-nonfinite.json"))

# ------------------------------------------------------------------ INT-010 rules vs advisory ML
t0 = time.monotonic()
cold = lambda seed: sim(seed, driving_scale=1.15)  # noqa: E731
cmp_rows = {}
for label, make in (("fault S01", lambda: sim(4100, (ScenarioInstance("S01", 60_000, 35_000),))), ("fault S05", lambda: sim(4100, (ScenarioInstance("S05", 60_000, 35_000),))),
                    ("cold stress 15000", lambda: cold(15000)), ("cold stress 15001", lambda: cold(15001)), ("cold stress 15002", lambda: cold(15002)), ("cold stress 15003", lambda: cold(15003))):
    _, _, rows_off, _, s_off = run("ml_off", make(), AnomalyAnalyzer(), ml_alerts=False)
    _, _, rows_on, _, s_on = run("ml_on", make(), AnomalyAnalyzer(), ml_alerts=True)
    _, _, rows_no, _, _ = run("ml_none", make(), None)
    cmp_rows[label] = {"rules_only": rule_events(rows_no), "app_policy_ml_advisory": rule_events(rows_off), "ml_alerts_on": [(r["kind"], r["trigger_ms"] / 1000) for r in rows_on if r["kind"] != "DATA_QUALITY"],
                       "advisory_count": len(s_off.advisory_ml)}
same_rules = all(v["rules_only"] == v["app_policy_ml_advisory"] for v in cmp_rows.values())
no_ml_event = all(not any(k == "ML_ANOMALY" for k, _ in v["app_policy_ml_advisory"]) for v in cmp_rows.values())
(folder / "rules-vs-ml.json").write_text(json.dumps(cmp_rows, indent=2), encoding="utf8")
reg.check("QA-REG-011", "AI-005 (DEF-001)", "App policy (ml_alerts=False): ML never opens an event; rule events identical with/without ML; ML hits are only advisory",
          "same trips with analyzer None / ml_alerts False / ml_alerts True", "rules_only == app policy; no ML_ANOMALY event in app policy", same_rules and no_ml_event, json.dumps({k: (len(v['rules_only']), len(v['app_policy_ml_advisory']), len(v['ml_alerts_on']), v['advisory_count']) for k, v in cmp_rows.items()}),
          rel(folder / "rules-vs-ml.json"), started=t0, notes="tuple = (rule events, app-policy events, ml_alerts=True events, advisory ML hits)")

# ------------------------------------------------------------------ INT-013 same-kind events inside an active window merge (by design)
path, sid, rows, evs, _ = run("dedupe", sim(4100, (ScenarioInstance("S07", 60_000, 18_000, 0.85, "flatline"), ScenarioInstance("S07", 90_000, 5_000, 0.85, "implausible"))))
sig = [(r["kind"], r["trigger_ms"] / 1000) for r in rows if r["kind"] == "MS_SIGNAL"]
dq = [(r["kind"], r["trigger_ms"] / 1000) for r in rows if r["kind"] == "DATA_QUALITY"]
win = [(e.samples[0].timestamp_ms / 1000, e.samples[-1].timestamp_ms / 1000) for e in evs if e.trigger.kind == "MS_SIGNAL"]
reg.check("QA-REG-013", "FR-005", "Explains the miss in QA-E2E-005b: a 5 s S07 fault at 90 s falls inside the still-open MS_SIGNAL window (68.0 s + 30 s) and is merged; its invalid readings still raise DATA_QUALITY",
          "S07 flatline 60 s/18 s + S07 implausible 90 s/5 s", "one MS_SIGNAL event whose window covers 90 s, plus a DATA_QUALITY event at ~90 s (documented same-kind merge, REMAINING_RISKS #9)",
          len(sig) == 1 and win and win[0][0] <= 90.0 <= win[0][1] and any(abs(t - 90.0) < 1.0 for _, t in dq), f"MS_SIGNAL={sig} window={win}; DATA_QUALITY={dq}",
          notes="By design since DC-FIX-001 (one event per kind while its window is open); a second fault of the same kind within 30 s is not given its own event.")

# ------------------------------------------------------------------ INT-011 SQLite integrity of every temp DB
issues = []
for p in dbs:
    if not p.exists():
        continue
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    ic = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    uv = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    if ic != "ok" or fk or uv != 2:
        issues.append((p.name, ic, len(fk), uv))
reg.check("QA-REG-012", "DATA-002", "All temp databases pass integrity_check/foreign_key_check and have user_version=2", f"{len(dbs)} databases written by this script", "none with issues", not issues, f"checked={len(dbs)} issues={issues}")

reg.save()
