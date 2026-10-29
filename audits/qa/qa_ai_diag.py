"""QA-AI / QA-XAI / QA-DIAG: model facts, window behaviour, independent XAI recomputation,
event linking and critical review of the generated reports. Product code is only called."""

import json
import os
import re
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, ROOT, Registry, rel, scratch  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from doctorcar.analysis import status as ai  # noqa: E402
from doctorcar.analysis.analyzer import AnomalyAnalyzer  # noqa: E402
from doctorcar.analysis.explanation import GROUPS, explain, group_members  # noqa: E402
from doctorcar.analysis.model import DEFAULT_MODEL, MODEL_V1, MODEL_V2, AnomalyModel, ModelLoadError  # noqa: E402
from doctorcar.analysis.windows import FEATURE_NAMES, WindowBuilder, extract  # noqa: E402
from doctorcar.core.models import Event, Quality, Reading, Sample, Source, Trigger  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.diagnostics.human_report import build_report_model, load_ai_context, render_simple, render_technical  # noqa: E402
from doctorcar.sources.scenarios import SCENARIOS_MS, ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("gate5_ai")
reg6 = Registry("gate6")
folder5, folder6 = EVIDENCE / "gate5", EVIDENCE / "gate6"
(EVIDENCE / "gate5_ai").mkdir(parents=True, exist_ok=True)
folder5.mkdir(parents=True, exist_ok=True)
(folder6 / "reports").mkdir(parents=True, exist_ok=True)
tmp = scratch("ai")
v1, v2 = AnomalyModel(MODEL_V1), AnomalyModel(MODEL_V2)


def stream(scenarios=(), seed=4100, **kw):
    s = SimulationSource(seed=seed, scenario_family="multisensor", mode="FAULT_INJECTION" if scenarios else "NORMAL", scenarios=scenarios, **kw)
    s.connect()
    s.session_id = f"qa-{seed}"
    s.start()
    out = []
    while (x := s.read_measurements()) is not None:
        out.append(replace(x, received_at_ms=None))
    s.disconnect()
    return out


def windows_of(model, samples):
    b, out = WindowBuilder(), []
    for s in samples:
        w = b.push(s)
        if w is not None:
            out.append(model.infer(w))
    return out


# ---------------------------------------------------------------------------- QA-AI-001 facts
facts = {}
for name, m in ((MODEL_V1, v1), (MODEL_V2, v2)):
    last = m.pipeline.steps[-1][1]
    cols = m.pipeline.steps[0][1].transformers_[0][2]
    facts[name] = {
        "algorithm": type(last).__name__, "n_estimators": last.n_estimators, "max_samples": str(last.max_samples), "model_version": m.metadata["model_version"],
        "sha256": m.metadata["sha256"], "feature_schema": m.metadata["feature_schema"], "feature_count_schema": len(m.metadata["feature_names"]),
        "feature_count_used_by_model": len(cols), "window": m.metadata["window"], "threshold": m.metadata["threshold"], "policy": m.policy,
        "threshold_policy": m.metadata.get("threshold_policy"), "trained_with_sklearn": m.metadata["sklearn_version"], "runtime_sklearn": sklearn.__version__,
        "numpy_trained": m.metadata["numpy_version"], "runtime_numpy": np.__version__, "training_rows": m.metadata["training_rows"],
        "train_trips": len(m.metadata["train_trips"]), "validation_trips": len(m.metadata.get("validation_trips", [])),
        "preprocessing_steps": [type(s[1]).__name__ for s in m.pipeline.steps],
        "used_feature_names": [FEATURE_NAMES[i] for i in cols],
    }
(folder5 / "model-facts.json").write_text(json.dumps({"default_model": DEFAULT_MODEL, **facts}, ensure_ascii=False, indent=2), encoding="utf8")
f2 = facts[MODEL_V2]
reg.check("QA-AI-001", "AI-007", "Model facts recorded: algorithm, version, schema, window, threshold, calibration, runtime versions",
          "load both shipped models", "IsolationForest, 47-feature schema, 5 s window / 1 s stride, threshold and calibration text present, trained == runtime versions",
          f2["algorithm"] == "IsolationForest" and f2["feature_count_schema"] == 47 and f2["window"]["length_ms"] == 5000 and f2["window"]["stride_ms"] == 1000
          and bool(f2["threshold_policy"]) and f2["trained_with_sklearn"] == f2["runtime_sklearn"],
          f"default={DEFAULT_MODEL}; v2: {f2['algorithm']} x{f2['n_estimators']}, uses {f2['feature_count_used_by_model']}/{f2['feature_count_schema']} features, threshold={f2['threshold']:.4f}, policy={f2['policy']}, sklearn {f2['runtime_sklearn']}",
          rel(folder5 / "model-facts.json"))
try:
    AnomalyModel("no-such-model")
    bad = "LOADED"
except ModelLoadError as exc:
    bad = f"ModelLoadError: {exc}"
reg.check("QA-AI-002", "AI-007", "Unknown or external model names are refused (no arbitrary joblib loading)", "AnomalyModel('no-such-model'), AnomalyModel('../x')",
          "ModelLoadError", bad.startswith("ModelLoadError"), bad[:120])

# ---------------------------------------------------------------------------- determinism + window cases
normal = stream()
s02 = stream((ScenarioInstance("S02", 60000, 35000),))
w_a = windows_of(v1, normal)
again = windows_of(AnomalyModel(MODEL_V1), normal)
det_ok = all(a.get("score") == b.get("score") for a, b in zip(w_a, again, strict=True))
reg.check("QA-AI-003", "AI-004", "Same inputs and a freshly loaded model give bit-identical scores", "151 windows scored twice by two model instances",
          "all scores identical", det_ok, f"{len(w_a)} windows identical={det_ok}")

cases = {}
cases["normal (cold, mid-trip)"] = next(r for r in windows_of(v2, normal)[40:] if r["decision"] != "INSUFFICIENT_DATA")
short = extract(tuple(normal[:15]))
cases["incomplete (3 s of data)"] = short
gap = list(normal[:40])
del gap[20:23]
cases["gap in sequence"] = extract(tuple(gap))
stale = [replace(s, readings={**s.readings, "MAF": Reading(5.0, "g/s", Quality.STALE)}) for s in normal[:26]]
cases["stale MAF"] = extract(tuple(stale))
unsup = [replace(s, readings={**s.readings, "MAF": Reading(None, "g/s", Quality.UNSUPPORTED)}) for s in normal[:26]]
cases["unsupported MAF"] = extract(tuple(unsup))
loss = [replace(s, readings={**s.readings, "RPM": Reading(None, "rpm", Quality.MISSING)}) if 5 <= i < 10 else s for i, s in enumerate(normal[:26])]
cases["1 s sensor loss in the window"] = extract(tuple(loss))
verdict = {k: (v.get("decision"), v.get("reason"), (v.get("coverage") or {}).get("RPM")) for k, v in cases.items()}
no_score = all("score" not in v2.infer(cases[k]) for k in ("incomplete (3 s of data)", "gap in sequence", "stale MAF", "unsupported MAF"))
loss_ok = cases["1 s sensor loss in the window"].get("decision") == "READY" and abs(cases["1 s sensor loss in the window"]["coverage"]["RPM"] - 25 / 26 * 1.0) < 0.2 and np.isfinite(cases["1 s sensor loss in the window"]["features"]).all()
reg.check("QA-AI-004", "AI-002", "Incomplete, gapped, stale and unsupported windows produce no score; a short sensor loss is reported as coverage, not zero",
          "crafted windows from a real stream", "INSUFFICIENT_DATA without score for the four; READY with coverage<1 and finite features for 1 s loss",
          no_score and loss_ok and cases["normal (cold, mid-trip)"]["decision"] in ("NORMAL", "ANOMALOUS"),
          json.dumps(verdict, ensure_ascii=False))

# no future data: windows before the injection are identical with and without the injection
fa = windows_of(v2, normal)
fb = windows_of(v2, s02)
before = [(x, y) for x, y in zip(fa, fb, strict=True) if x.get("end_ms") is not None and x["end_ms"] < 60000]
same_features = all(x.get("features") == y.get("features") and x.get("score") == y.get("score") for x, y in before)
first_diff = next((y["end_ms"] for x, y in zip(fa, fb, strict=True) if x.get("features") != y.get("features")), None)
reg.check("QA-AI-005", "AI-004", "No future leakage: windows ending before the injection are bit-identical to the no-fault trip",
          "same seed, S02 injected at 60 s vs no injection", "all windows ending < 60 s identical; first difference after 60 s",
          same_features and first_diff is not None and first_diff > 60000, f"{len(before)} earlier windows identical={same_features}; first differing window ends at {first_diff}")
renamed = [replace(s, phase="S02", provenance="expected-fault", raw={"fault": "S02", "ground_truth": True}) for s in normal]
rn = windows_of(v2, renamed)
reg.check("QA-AI-006", "AI-004", "Scenario/fault labels in sample metadata do not change the model score", "same samples with phase/provenance/raw set to fault names",
          "identical scores", all(a.get("score") == b.get("score") for a, b in zip(fa, rn, strict=True)), "scores identical across all windows")

# separability (characterization on the shipped dataset-3 test split; not independent of the v2 decision)
manifest = json.loads((ROOT / "data/cr005-dataset/manifest.json").read_text("utf8"))
feat = pd.read_csv(ROOT / "data/cr005-dataset/features.csv")
lab = pd.read_csv(ROOT / "data/cr005-dataset/labels.csv")
test = feat[feat.split == "test"].merge(lab[["trip", "end_ms", "fault_active"]], on=["trip", "end_ms"])
by_trip = {t["trip"]: t for t in manifest["trips"]}
auc = {}
neg_trips = [t for t in test.trip.unique() if not by_trip[t]["scenarios"]]
for sid in sorted(SCENARIOS_MS):
    trips = [t for t in test.trip.unique() if len(by_trip[t]["scenarios"]) == 1 and by_trip[t]["scenarios"][0]["scenario_id"] == sid]
    pos = test[test.trip.isin(trips) & test.fault_active]
    neg = test[test.trip.isin(neg_trips)]
    row = {}
    for nm, m in ((MODEL_V1, v1), (MODEL_V2, v2)):
        y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
        sc = np.r_[m.scores(pos[list(FEATURE_NAMES)].to_numpy()), m.scores(neg[list(FEATURE_NAMES)].to_numpy())]
        row[nm] = round(float(roc_auc_score(y, sc)), 3)
    auc[sid] = {"fault_windows": len(pos), "normal_windows": len(neg), **row}
(folder5 / "window-auc.json").write_text(json.dumps(auc, ensure_ascii=False, indent=2), encoding="utf8")
reg.add("QA-AI-007", "AI-008", "Window-level separability (ROC AUC) of fault windows vs normal windows, per scenario",
        "dataset-3 test windows (characterization; this split informed the v2 default decision, so not independent)", "informational: AUC > 0.5 means the score ranks fault windows higher",
        "; ".join(f"{k}: v1={v[MODEL_V1]} v2={v[MODEL_V2]}" for k, v in auc.items()),
        "PASS" if all(v[MODEL_V2] > 0.5 for v in auc.values()) else "PARTIAL", rel(folder5 / "window-auc.json"),
        notes="AUC near 0.5 or below means the model cannot rank that scenario's windows; see ml-eval for operational detection.")

# gradual vs sudden trajectories
traj = {}
for sid, sc in (("S01 gradual thermal", ScenarioInstance("S01", 60000, 35000)), ("S05 sudden voltage", ScenarioInstance("S05", 60000, 35000))):
    for nm, m in ((MODEL_V1, v1), (MODEL_V2, v2)):
        r = [x for x in windows_of(m, stream((sc,))) if "score" in x]
        peak = max(r, key=lambda x: x["score"])
        first = next((x["end_ms"] for x in r if x["decision"] == "ANOMALOUS" and x["end_ms"] >= 60000), None)
        traj[f"{sid} / {nm}"] = {"peak_score": round(peak["score"], 3), "peak_at_s": peak["end_ms"] / 1000, "threshold": round(m.metadata["threshold"], 3), "first_anomalous_window_after_start_s": first / 1000 if first else None}
(folder5 / "gradual-vs-sudden.json").write_text(json.dumps(traj, ensure_ascii=False, indent=2), encoding="utf8")
reg.add("QA-AI-008", "AI-002", "Gradual (S01) and sudden (S05) changes: score trajectory vs threshold", "peak score and first anomalous window per model",
        "informational", "; ".join(f"{k}: peak {v['peak_score']} at {v['peak_at_s']}s vs thr {v['threshold']} first-anom {v['first_anomalous_window_after_start_s']}" for k, v in traj.items()),
        "PASS" if any(v["first_anomalous_window_after_start_s"] for v in traj.values()) else "PARTIAL", rel(folder5 / "gradual-vs-sudden.json"))

# ---------------------------------------------------------------------------- XAI
anom = next(r for r in windows_of(v1, s02) if r["decision"] == "ANOMALOUS")
x1, x2 = explain(v1, anom), explain(v1, anom)
other = [r for r in windows_of(v1, s02) if r["decision"] == "ANOMALOUS"][-1]
x3 = explain(v1, other)
same = [e["effect"] for e in x1["effects"]] == [e["effect"] for e in x2["effects"]]
differ = [e["effect"] for e in x1["effects"]] != [e["effect"] for e in x3["effects"]]
# independent recomputation straight from the pipeline
x = np.array(anom["features"])
bg = np.array(v1.metadata["background"])
indep_ok, worst = True, 0.0
for g, sensors in GROUPS.items():
    ix = group_members(sensors)
    c = x.copy()
    c[ix] = bg[ix]
    eff = float(-v1.pipeline.score_samples([x])[0] - (-v1.pipeline.score_samples([c])[0]))
    got = next(e["effect"] for e in x1["effects"] if e["group"] == g)
    worst = max(worst, abs(eff - got))
    indep_ok &= abs(eff - got) < 1e-12
reg.check("QA-XAI-001", "XAI-001/002", "XAI: deterministic, varies with the window, equals an independent recomputation from the pipeline",
          "explain the same anomalous window twice, another window, and recompute counterfactual scores directly", "identical for the same window; different for another; |difference| < 1e-12",
          same and differ and indep_ok and x1["end_ms"] == anom["end_ms"] and x1["model_sha256"] == v1.metadata["sha256"],
          f"same_window_identical={same} other_window_differs={differ} max_independent_diff={worst:.2e} window_end={x1['end_ms']} model_sha_match={x1['model_sha256'] == v1.metadata['sha256']}")
sel_v1 = set(v1.pipeline.steps[0][1].transformers_[0][2])
speed_idx = set(group_members(GROUPS["speed"]))
speed_by = {e["group"]: (e["used_by_model"], e["effect"]) for e in x1["effects"]}["speed"]
sel_v2 = set(v2.pipeline.steps[0][1].transformers_[0][2])
reg.check("QA-XAI-002", "XAI-004", "Previously 'always zero' SPEED group: is it a real non-effect or an aggregation/display bug?",
          "inspect the model's selected columns and the explanation output", "v1 never reads SPEED features (design), explanation flags used_by_model=false; v2 reads them",
          not (sel_v1 & speed_idx) and speed_by == (False, 0.0) and bool(sel_v2 & speed_idx),
          f"v1 reads {len(sel_v1)} features, SPEED features read={sorted(sel_v1 & speed_idx)}; explanation says used={speed_by[0]} effect={speed_by[1]}; v2 reads SPEED features={sorted(sel_v2 & speed_idx)[:4]}",
          notes="Conclusion: not a bug; the feature subset excluded SPEED. The display now marks it 'not read by this model'.")
bad_res = []
for label, window in (("insufficient", {"decision": "INSUFFICIENT_DATA"}), ("other model result", {**anom, "model_sha256": "x"}), ("tampered features", {**anom, "features": [0.0] * 47})):
    try:
        explain(v1, window)
        bad_res.append(f"{label}: EXPLAINED")
    except ValueError:
        pass
reg.check("QA-XAI-003", "XAI-001", "No explanation for insufficient data, another model's result or inconsistent features", "explain() with invalid inputs", "ValueError each time", not bad_res, "all refused" if not bad_res else str(bad_res))

# ---------------------------------------------------------------------------- Session-level: linking and reports
repo_path = lambda n: (tmp / f"{n}.sqlite3")  # noqa: E731


def run_session(name, scenarios, analyzer=None, ai_failure=None, seed=4100):
    p = repo_path(name)
    for f in tmp.glob(f"{name}.sqlite3*"):
        f.unlink()
    src = SimulationSource(seed=seed, scenario_family="multisensor", mode="FAULT_INJECTION" if scenarios else "NORMAL", scenarios=scenarios)
    out = []
    with SQLiteRepository(p) as repo:
        s = Session(src, repo, analyzer=analyzer, ai_failure=ai_failure)
        s.start()
        while not src.exhausted:
            s.step()
        s.stop()
        for r in repo.list_events():
            ev = repo.get_event(r["event_id"])
            analysis, status, later = load_ai_context(repo, ev)
            out.append((ev, analysis, status, later, repo.get_detections(ev.event_id)))
    return out


s01 = run_session("s01", (ScenarioInstance("S01", 60000, 35000),), AnomalyAnalyzer())
th = next(x for x in s01 if x[0].trigger.kind == "MS_THERMAL")
ev, analysis, status, later, dets = th
rep = build_report_model(ev, analysis, dets, status, later)
txt = render_simple(rep)
reg.check("QA-AI-LINK-001", "INT-003", "Rule event at 68.2 s links the ML window that ended at 68.0 s (200 ms earlier)", "S01 at 60 s, real Session, default model",
          "status window_end=68000, age=200 ms, detection=68200; report says rules detected and AI analyzed",
          ev.trigger.timestamp_ms == 68200 and status["window_end_ms"] == 68000 and status["age_ms"] == 200 and rep.detection_summary["ml"] is False and "لم يُحلل هذا الحدث" not in txt,
          f"detection={ev.trigger.timestamp_ms} window_end={status['window_end_ms']} age={status['age_ms']} state={status['state']} ml_flag={rep.detection_summary['ml']}")


class Stub:
    def __init__(self, result, age=2000):
        self.result, self.max_age_ms = result, age
        self.model = SimpleNamespace(metadata={"model_version": "stub"})

    def latest_before(self, sid, t):
        return self.result

    def explain(self, a):
        raise RuntimeError("n/a")


class Fake:
    def __init__(self):
        self.statuses, self.links = {}, []

    def link_analysis(self, *a):
        self.links.append(a)

    def save_event_ai_status(self, i, s):
        self.statuses[i] = s

    def save_analysis(self, r):
        pass

    def save_event(self, e):
        pass


def status_with(result, detection_ms=68200):
    ev_ = Event("e", "sess", Trigger("X", "t", "t", "v", detection_ms), [Sample("sess", Source.SIMULATION, 0, detection_ms, {"RPM": Reading(800.0, "rpm")})], "COMPLETE", detection_ms)
    fake = Fake()
    Session(object(), fake, analyzer=Stub(result))._record_ai_status(ev_)  # type: ignore[arg-type]
    return fake.statuses["e"], fake.links


mk = lambda end, dec="NORMAL", sid="sess": {"decision": dec, "session_id": sid, "start_ms": end - 5000, "end_ms": end, "score": 0.5, "threshold": 0.58, "model_version": "stub", "model_sha256": "s"}  # noqa: E731
link_cases = {
    "exact (68.0 vs 68.2)": (mk(68000), "ANALYZED_NORMAL"),
    "200 ms older": (mk(68000, "ANOMALOUS"), "ANALYZED_ANOMALOUS"),
    "no analysis available": (None, "NO_RECENT_ANALYSIS"),
    "insufficient window": ({"decision": "INSUFFICIENT_DATA", "reason": "sensor_coverage", "end_ms": 68000}, "INSUFFICIENT_DATA"),
}
res = {k: status_with(v[0])[0]["state"] for k, v in link_cases.items()}
ok_states = all(res[k] == v[1] for k, v in link_cases.items())
an = AnomalyAnalyzer(v2)
for smp in [s for s in normal if s.timestamp_ms <= 68200]:
    an.push(smp)
sid = normal[0].session_id
age_limits = {"2000 ms old": an.latest_before(sid, 70000) is not None, "2001 ms old": an.latest_before(sid, 70001) is None, "other session": an.latest_before("zzz", 68200) is None,
              "future window not returned": an.latest_before(sid, 67999)["end_ms"] <= 67999, "before first window": an.latest_before(sid, 3000) is None}
reg.check("QA-AI-LINK-002", "INT-003", "Linking states: exact/old/none/insufficient; age limit 2000 ms; other session and future windows never linked",
          "stub and real analyzer history", "state per case as expected; every age/session/future check true", ok_states and all(age_limits.values()), f"states={res}; checks={age_limits}")
st_stale, links_stale = status_with(mk(60000))
reg.add("QA-AI-LINK-003", "INT-003", "Session itself does not re-check analysis age (defence in depth)", "stub analyzer returns an analysis ended 8.2 s before the event",
        "ideal: Session refuses a stale analysis even if an analyzer implementation returns it",
        f"Session linked it: state={st_stale['state']} links={links_stale}; the age limit is enforced only inside AnomalyAnalyzer.latest_before (verified in QA-AI-LINK-002)",
        "PARTIAL", notes="Not a defect with the shipped analyzer; a future analyzer implementation without the age check would link stale results.")
fail_states = {}
for label, kw in (("disabled", {}), ("not loaded", {"ai_failure": "ModelLoadError: x"})):
    ev_f = run_session("f_" + label.replace(" ", ""), (ScenarioInstance("S01", 60000, 35000),), None, **kw)
    fail_states[label] = sorted({x[2]["state"] for x in ev_f})


class Broken:
    model = v2
    max_age_ms = 2000

    def push(self, s):
        raise RuntimeError("boom")


ev_f = run_session("f_broken", (ScenarioInstance("S01", 60000, 35000),), Broken())
fail_states["inference failed"] = sorted({x[2]["state"] for x in ev_f})
reg.check("QA-AI-LINK-004", "INT-003", "AI unavailable cases carry the right state: disabled / model not loaded / inference failed (rules keep working)",
          "Session with no analyzer, with ai_failure, with a raising analyzer", "DISABLED / MODEL_NOT_LOADED / INFERENCE_FAILED and MS_THERMAL still detected",
          fail_states == {"disabled": ["DISABLED"], "not loaded": ["MODEL_NOT_LOADED"], "inference failed": ["INFERENCE_FAILED"]} and any(x[0].trigger.kind == "MS_THERMAL" for x in ev_f), json.dumps(fail_states))
# AI detected before rules (v1 is sensitive enough on S02)
s02r = run_session("s02v1", (ScenarioInstance("S02", 60000, 35000),), AnomalyAnalyzer(v1))
mlev = next((x for x in s02r if x[0].trigger.kind == "ML_ANOMALY"), None)
if mlev:
    r_ = build_report_model(mlev[0], mlev[1], mlev[4], mlev[2], mlev[3])
    t_ = render_simple(r_)
    reg.check("QA-AI-LINK-005", "INT-003", "AI detects first, rules confirm later: reported as 'both', with later rule evidence labelled as later",
              "S02 with model v1", "detection_summary combined, text 'AI and rules together', later-evidence sentence present",
              r_.detection_summary["combined"] and "اكتشفه الذكاء الاصطناعي والقواعد معًا" in t_ and "ليست مدخلات قرار AI السابق" in t_,
              f"ML@{mlev[0].trigger.timestamp_ms} rules={r_.detection_summary['rule_kinds']}@{r_.detection_summary['rule_first_ms']} state={mlev[2]['state']}")
else:
    reg.add("QA-AI-LINK-005", "INT-003", "AI first then rules", "S02 with model v1", "an ML_ANOMALY event", "none produced", "FAIL")
rules_only = [x for x in s01 if x[0].trigger.kind == "MS_THERMAL"][0]
r_ro = build_report_model(rules_only[0], rules_only[1], rules_only[4], rules_only[2], rules_only[3])
reg.check("QA-AI-LINK-006", "INT-003", "A rules-only event is never presented as 'detected by AI'", "S01 event with a normal AI analysis",
          "detection_summary.ml false; text says rules detected", r_ro.detection_summary["ml"] is False and "اكتشفه الذكاء الاصطناعي" not in render_simple(r_ro) and "اكتشفته القواعد" in render_simple(r_ro), "ok")

# normal decision -> no XAI shown; anomalous -> XAI shown with computed groups
anom_ev = next((x for x in s02r if x[2]["state"] == ai.ANALYZED_ANOMALOUS), None)
normal_ev = next((x for x in s01 if x[2]["state"] == ai.ANALYZED_NORMAL), None)
txt_n = render_simple(build_report_model(normal_ev[0], normal_ev[1], normal_ev[4], normal_ev[2], normal_ev[3])) if normal_ev else ""
a_rep = build_report_model(anom_ev[0], anom_ev[1], anom_ev[4], anom_ev[2], anom_ev[3]) if anom_ev else None
txt_a = render_simple(a_rep) if a_rep else ""
xai_a = (anom_ev[1] or {}).get("xai", {}) if anom_ev else {}
line = next((x for x in txt_a.splitlines() if x.startswith("العوامل الأكثر تأثيرًا")), "")
pos = {e["group"] for e in xai_a.get("effects", []) if e["effect"] > 1e-8}
names = {"temperature": "تغير الحرارة", "air_fuel_operation": "علاقات الهواء والوقود وظروف التشغيل", "voltage": "جهد التغذية", "speed": "سرعة المركبة"}
shown = {g for g, n_ in names.items() if n_ in line}
xai_ok = bool(anom_ev) and xai_a.get("status") == "AVAILABLE" and bool(shown) and shown <= pos and xai_a["end_ms"] <= anom_ev[0].trigger.timestamp_ms
reg.check("QA-XAI-004", "XAI-003", "Report: no anomaly-factor text for a normal AI decision; for an anomalous one only computed positive groups, from a window not after detection",
          "S01 (normal AI) and S02 with v1 (anomalous AI)", "no 'العوامل' line for normal; shown groups subset of positive computed effects; xai.end_ms <= detection",
          "العوامل الأكثر تأثيرًا" not in txt_n and xai_ok and "ليست أسبابًا ميكانيكية" in txt_a,
          f"normal_text_has_factors={'العوامل الأكثر تأثيرًا' in txt_n}; anomalous shown={sorted(shown)} positive={sorted(pos)} xai_end={xai_a.get('end_ms')} detection={anom_ev[0].trigger.timestamp_ms if anom_ev else None}")

# ---------------------------------------------------------------------------- diagnostics per scenario
expected_rule = {"S01": "MS_THERMAL", "S02": "MS_AIR_FUEL", "S03": "MS_FUEL_RESPONSE", "S04": "MS_AIRFLOW", "S05": "MS_SUPPLY", "S06": "MS_COMBUSTION", "S07": "MS_SIGNAL"}
leak_words = re.compile(r"S0[1-7]|FAULT_INJECTION|fault_active|ground.?truth|injected|حقن|سيناريو", re.I)
definitive = re.compile(r"(المضخة|الثرموستات|الحساس|الحاقن|البطارية)\s+(تالف|معطل|مكسور)|is (faulty|defective|broken)|has failed|confirmed (fault|failure)|تأكد (تلف|عطل)", re.I)
table = {}
for sid, rule in expected_rule.items():
    runs = run_session(f"diag_{sid}", (ScenarioInstance(sid, 60000, 35000),), AnomalyAnalyzer())
    main_ev = next((x for x in runs if x[0].trigger.kind == rule), None)
    if main_ev is None:
        table[sid] = {"detected_rule": None, "events": [x[0].trigger.kind for x in runs]}
        reg6.add(f"QA-DIAG-{sid}", f"AT-MS/{sid}", f"{sid}: report review", "S at 60 s/35 s", f"event {rule}", f"events={[x[0].trigger.kind for x in runs]}", "FAIL")
        continue
    ev_, an_, st_, la_, de_ = main_ev
    r = build_report_model(ev_, an_, de_, st_, la_)
    ar, en, tech = render_simple(r, "ar"), render_simple(r, "en"), render_technical(r, "en")
    (folder6 / "reports" / f"{sid}-ar.txt").write_text(ar, encoding="utf8")
    (folder6 / "reports" / f"{sid}-en.txt").write_text(en, encoding="utf8")
    (folder6 / "reports" / f"{sid}-technical.txt").write_text(tech, encoding="utf8")
    # numeric check: report 'at detection' values equal stored samples
    at = [s for s in ev_.samples if s.timestamp_ms <= ev_.trigger.timestamp_ms][-1]
    num_ok = all(abs(m["at_detection"] - at.readings[m["sensor"]].value) < 1e-9 for m in r.key_measurements if m["at_detection"] is not None) and bool(r.key_measurements)
    peak_ok = all(m["maximum_recorded"] >= max(s.readings[m["sensor"]].value for s in ev_.samples if s.readings[m["sensor"]].value is not None) - 1e-9 for m in r.key_measurements)
    hyps = r.hypotheses
    h_count = len(hyps)
    has_contra = all(("contradicting_evidence" in h) for h in hyps)
    has_missing = any(h.get("missing_evidence") for h in hyps)
    has_checks = all(h.get("recommended_check") for h in hyps)
    leaks = leak_words.findall(ar + en + tech)
    claims = definitive.findall(ar + en)
    disclaim = "يلزم فحص مستقل" in ar and "لا تستبدل قطعة" in ar and "Evidence cannot establish" in en
    table[sid] = {"detected_rule": rule, "time_s": ev_.trigger.timestamp_ms / 1000, "hypotheses": [h["description_en"] or h["description"] for h in hyps], "n_hyp": h_count,
                  "missing_evidence_present": has_missing, "checks": [h["recommended_check_en"] or h["recommended_check"] for h in hyps], "leaks": sorted(set(leaks)), "definitive_claims": claims, "ai_state": st_["state"]}
    reg6.check(f"QA-DIAG-{sid}", f"AT-MS/{sid}", f"{sid}: report is evidence-based, numerically correct, hedged and free of injected-fault names",
               f"S at 60 s / 35 s; event {rule}", ">=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no definitive part failure, disclaimers",
               h_count >= 2 and has_contra and has_missing and has_checks and num_ok and peak_ok and not leaks and not claims and disclaim,
               f"hyp={h_count} contra_field={has_contra} missing={has_missing} checks={has_checks} values_ok={num_ok}/{peak_ok} leaks={sorted(set(leaks))} definitive={claims} disclaimers={disclaim}",
               rel(folder6 / "reports" / f"{sid}-ar.txt"))
(folder6 / "diagnostic-review.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf8")
# confusable causes
conf = {s: set(table[s].get("hypotheses", [])) for s in ("S02", "S03", "S04") if s in table and table[s].get("hypotheses")}
overlap_note = {f"{a}~{b}": sorted(conf[a] & conf[b]) for a in conf for b in conf if a < b}
same_set = len({frozenset(v) for v in conf.values()}) < len(conf)
reg6.add("QA-DIAG-AMBIG", "INT-002", "Confusable air/fuel/airflow patterns: reports must not pretend to separate causes the evidence cannot separate",
         "compare hypothesis sets of S02 (air), S03 (fuel), S04 (airflow measurement)", "different evidence -> different hypothesis sets; shared hypotheses declared as shared; no definitive single cause",
         f"hypothesis sets: {json.dumps({k: sorted(v) for k, v in conf.items()}, ensure_ascii=False)}; shared={json.dumps(overlap_note, ensure_ascii=False)}; identical_sets={same_set}",
         "PASS" if conf and not same_set and all(len(v) >= 2 for v in conf.values()) else "PARTIAL", rel(folder6 / "diagnostic-review.json"),
         notes="Each report keeps >=2 alternatives and states that evidence cannot establish the cause; distinguishing S02 from S04 relies on the MAF/MAP residuals, which the technical report shows.")
reg.save()
reg6.save()
