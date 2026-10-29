"""DC-FIX-001 re-run of the DC-QA-001 52-trip ML evaluation with the packaged v3 added.
Output goes to docs/evidence/remediation/gate5 (original QA evidence untouched). NOTE: these
seeds were already seen during DC-QA-001, so this is a before/after comparison, not the
independent final test (that is the cr006 test split).
QA-AI: independent Rules / ML / Combined evaluation on trips never used for training,
calibration or the earlier acceptance test (seeds 9000+). Read-only use of the shipped models."""

import csv
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qa"))
from qa_common import EVIDENCE, Registry, rel  # noqa: E402

from doctorcar.analysis import benchmark as b  # noqa: E402
from doctorcar.analysis.analyzer import DetectionPolicy, PersistenceGate  # noqa: E402
from doctorcar.analysis.model import MODEL_V1, MODEL_V2, MODEL_V3, AnomalyModel  # noqa: E402
from doctorcar.analysis.windows import WindowBuilder  # noqa: E402
from doctorcar.monitoring.event_detector import EventDetector  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402

reg = Registry("gate5")
folder = EVIDENCE.parent / "remediation" / "gate5"
folder.mkdir(parents=True, exist_ok=True)
rng = random.Random(99)
specs = []
for i in range(24):
    specs.append(b.TripSpec(f"qa-n{i:02d}", "qa", 9000 + i, round(rng.uniform(0.85, 1.15), 4), i % 2 == 1))
starts, durs, sevs = (50000, 60000, 70000, 80000), (15000, 25000, 35000, 25000), (0.7, 1.0, 0.85, 1.0)
variants = {"S07": ("default", "flatline", "implausible", "default")}
n = 0
for sid in (f"S0{i}" for i in range(1, 8)):
    for j in range(4):
        v = variants.get(sid, ("default",) * 4)[j]
        specs.append(b.TripSpec(f"qa-{sid}-{j}", "qa", 9100 + n, round(rng.uniform(0.85, 1.15), 4), j % 2 == 0,
                                (ScenarioInstance(sid, starts[j], durs[j], sevs[j], v),)))
        n += 1
for i in range(12):  # stress: cold start with the highest driving scales (known weak region)
    specs.append(b.TripSpec(f"qa-stress{i:02d}", "stress", 9300 + i, round(rng.uniform(1.08, 1.15), 4), False))
models = {name: AnomalyModel(name) for name in (MODEL_V1, MODEL_V2, MODEL_V3)}
t0 = time.monotonic()
raw = {}
windows = {name: {"qa": [], "stress": []} for name in models}
for k, spec in enumerate(specs):
    det, builder = EventDetector(), WindowBuilder()
    gates = {nm: PersistenceGate(float(m.metadata["threshold"]), DetectionPolicy(int(m.policy["consecutive"]), float(m.policy["hysteresis"]))) for nm, m in models.items()}
    rules, ml = [], {nm: [] for nm in models}
    for r in b.stream_trip(spec):
        for t in det.evaluate_trigger(r.sample, r.issues):
            rules.append((t.kind, t.timestamp_ms))
        w = builder.push(r.sample)
        if w is None:
            continue
        for nm, m in models.items():
            inf = m.infer(w)
            sc = inf.get("score")
            if gates[nm].update(float(sc) if sc is not None else None):
                ml[nm].append(w["end_ms"])
            if sc is not None:
                windows[nm][spec.split].append((b.fault_active(spec, w["end_ms"]), inf["decision"] == "ANOMALOUS"))
    raw[spec.trip] = {"rules": b.dedupe(rules), "ml": ml}
    print(f"{k + 1}/{len(specs)} {spec.trip} scale={spec.scale} rules={len(raw[spec.trip]['rules'])} v1={len(ml[MODEL_V1])} v2={len(ml[MODEL_V2])} v3={len(ml[MODEL_V3])} ({time.monotonic() - t0:.0f}s)", flush=True)

main = [s for s in specs if s.split == "qa"]
stress = [s for s in specs if s.split == "stress"]
streams = {}
for label in ("rules", f"ml:{MODEL_V1}", f"ml:{MODEL_V2}", f"ml:{MODEL_V3}", f"combined:{MODEL_V1}", f"combined:{MODEL_V2}", f"combined:{MODEL_V3}"):
    streams[label] = {}
    for s in specs:
        r = raw[s.trip]
        if label == "rules":
            streams[label][s.trip] = [[a] for _, a in r["rules"]]
        elif label.startswith("ml:"):
            streams[label][s.trip] = [[a] for a in r["ml"][label[3:]]]
        else:
            streams[label][s.trip] = b.combine(r["rules"], r["ml"][label[9:]])
summary, per_scenario, stress_summary = {}, {}, {}
for label, per in streams.items():
    matched = [b.match_alarms(s, per[s.trip]) for s in main]
    summary[label] = b.summarize(matched, main)
    stress_matched = [b.match_alarms(s, per[s.trip]) for s in stress]
    stress_summary[label] = {"false_alarm_events": sum(len(m["false_alarms"]) for m in stress_matched), "trips": len(stress), "trips_with_alarm": sum(1 for m in stress_matched if m["alarms"])}
    for sid in (f"S0{i}" for i in range(1, 8)):
        ev = [e for m in matched for e in m["events"] if e["scenario"] == sid]
        d = sorted(e["delay_ms"] / 1000 for e in ev if e["detected"])
        per_scenario.setdefault(sid, {})[label] = {"events": len(ev), "detected": sum(e["detected"] for e in ev), "delay_median_s": d[len(d) // 2] if d else None}
win = {}
for nm in models:
    y = [r[0] for r in windows[nm]["qa"]]
    p = [r[1] for r in windows[nm]["qa"]]
    import numpy as np

    win[nm] = b.window_metrics(np.array(y), np.array(p), len(y) / 3600)
out = {"trips": {"normal": 24, "fault": 28, "stress_cold_high_scale": 12}, "event_level": summary, "window_level": win, "by_scenario": per_scenario,
       "stress_cold_high_scale": stress_summary, "match_rule": "alarm in [start, start+duration+10s] = detection; same-source alarms within 30 s = one event; rule+ML within 10 s = one combined event"}
(folder / "ml-eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf8")
with (folder / "ml-eval-alarms.csv").open("w", newline="", encoding="utf8") as f:
    wr = csv.writer(f)
    wr.writerow(["trip", "split", "scale", "warm", "scenarios", "stream", "alarm_times_s"])
    for s in specs:
        for label, per in streams.items():
            wr.writerow([s.trip, s.split, s.scale, s.warm, ";".join(f"{x.scenario_id}@{x.start_ms // 1000}+{x.duration_ms // 1000}" for x in s.scenarios), label, " ".join(f"{g[0] / 1000:.1f}" for g in per[s.trip])])

print(json.dumps({k: {x: v[x] for x in ('events','detected','recall','false_alarm_events','precision','false_alarms_per_hour') if x in v} for k,v in summary.items()}, indent=1))
print(json.dumps(stress_summary, indent=1))
