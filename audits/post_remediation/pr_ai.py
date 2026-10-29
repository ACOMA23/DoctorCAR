"""DC-VERIFY-002 AI / XAI / report regression for the default model v3 (read-only use of shipped models)."""

import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qa"))
import numpy as np  # noqa: E402
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402

from doctorcar.analysis.analyzer import AnomalyAnalyzer  # noqa: E402
from doctorcar.analysis.explanation import GROUPS, explain, group_members  # noqa: E402
from doctorcar.analysis.model import DEFAULT_MODEL, MODEL_V3, TRUSTED_SHA256, AnomalyModel  # noqa: E402
from doctorcar.analysis.windows import WindowBuilder, extract  # noqa: E402
from doctorcar.core.models import Quality, Reading  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.diagnostics.human_report import build_report_model, load_ai_context, render_simple, render_technical  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("ai_reports")
folder = EVIDENCE / "ai_reports"
(folder / "reports").mkdir(parents=True, exist_ok=True)
tmp = scratch("pr-ai")
ARABIC = re.compile(r"[؀-ۿ]")
v3 = AnomalyModel()


def stream(scen=(), seed=4100, **kw):
    s = SimulationSource(seed=seed, scenario_family="multisensor", mode="FAULT_INJECTION" if scen else "NORMAL", scenarios=tuple(scen), **kw)
    s.connect()
    s.session_id = f"v-{seed}"
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


# ------------------------------------------------------------------ AI-V3-001 identity
md = v3.metadata
reg.check("QA-V3-001", "AI-007", "Default model is cr006-iforest-v3, loaded through the trusted-SHA gate", "AnomalyModel() with no name",
          "DEFAULT_MODEL == cr006-iforest-v3 == MODEL_V3; metadata sha256 == TRUSTED_SHA256; IsolationForest; schema 47 features",
          DEFAULT_MODEL == MODEL_V3 == "cr006-iforest-v3" and md["sha256"] == TRUSTED_SHA256[MODEL_V3] and md["model_version"] == "iforest-cr006-v3" and len(md["feature_names"]) == 47
          and type(v3.pipeline.steps[-1][1]).__name__ == "IsolationForest",
          f"default={DEFAULT_MODEL} version={md['model_version']} sha={md['sha256'][:16]}.. threshold={md['threshold']:.4f} policy={v3.policy}")
try:
    AnomalyModel("no-such-model")
    refused = "LOADED"
except Exception as exc:  # noqa: BLE001
    refused = type(exc).__name__
reg.check("QA-V3-002", "AI-007", "Unknown model names are refused", "AnomalyModel('no-such-model')", "ModelLoadError", refused == "ModelLoadError", refused)

# ------------------------------------------------------------------ AI-V3-003 real inference
normal = stream()
s05 = stream((ScenarioInstance("S05", 60_000, 35_000),))
s01 = stream((ScenarioInstance("S01", 60_000, 35_000),))
wn = [w for w in windows_of(v3, normal) if "score" in w]
wf = [w for w in windows_of(v3, s05) if "score" in w]
wn2 = [w for w in windows_of(AnomalyModel(), normal) if "score" in w]
scores = np.array([w["score"] for w in wn])
det = all(a["score"] == b["score"] for a, b in zip(wn, wn2, strict=True))
peak_n, peak_f = max(w["score"] for w in wn), max(w["score"] for w in wf)
(folder / "v3-scores.json").write_text(json.dumps({"normal_windows": len(wn), "normal_min": float(scores.min()), "normal_max": float(scores.max()), "normal_std": float(scores.std()),
                                                   "fault_S05_peak": peak_f, "normal_peak": peak_n, "threshold": md["threshold"], "deterministic": det}, indent=2), encoding="utf8")
reg.check("QA-V3-003", "AI-001", "v3 produces real, finite, deterministic scores that vary with the data", "windows of a normal trip and an S05 trip, two model instances",
          "finite, std > 0, identical on a fresh instance, S05 peak differs from normal peak", bool(np.isfinite(scores).all()) and scores.std() > 0 and det and peak_f != peak_n,
          f"{len(wn)} windows, score {scores.min():.3f}..{scores.max():.3f} std={scores.std():.3f}; S05 peak={peak_f:.3f} vs normal peak={peak_n:.3f}; threshold={md['threshold']:.3f}; deterministic={det}", rel(folder / "v3-scores.json"))
before = [(a, b) for a, b in zip(windows_of(v3, normal), windows_of(v3, s05), strict=True) if a.get("end_ms") is not None and a["end_ms"] < 60_000]
renamed = [replace(s, phase="S05", provenance="expected-fault", raw={"fault": "S05", "ground_truth": True}) for s in normal]
reg.check("QA-V3-004", "AI-004", "No future/label leakage with v3: windows ending before the injection are bit-identical; scenario labels do not change scores",
          "same seed with/without S05 at 60 s; samples relabelled as fault", "identical features and scores", all(a.get("score") == b.get("score") and a.get("features") == b.get("features") for a, b in before)
          and all(x.get("score") == y.get("score") for x, y in zip(windows_of(v3, normal), windows_of(v3, renamed), strict=True)), f"{len(before)} pre-injection windows compared")
gap = list(normal[:40]); del gap[20:23]
stale = [replace(s, readings={**s.readings, "MAF": Reading(5.0, "g/s", Quality.STALE)}) for s in normal[:26]]
bad = [k for k, w in (("short", extract(tuple(normal[:15]))), ("gap", extract(tuple(gap))), ("stale", extract(tuple(stale)))) if "score" in v3.infer(w)]
reg.check("QA-V3-005", "AI-002", "Incomplete, gapped and stale windows get no score", "3 crafted windows", "no score for any", not bad, f"scored={bad}")

# ------------------------------------------------------------------ XAI on ANOMALOUS windows
anoms = []
for seed in range(15000, 15015):
    for w in windows_of(v3, stream(seed=seed, driving_scale=1.15)):
        if w.get("decision") == "ANOMALOUS":
            anoms.append((seed, w))
    if len(anoms) >= 6:
        break
for w in wf:
    if w["decision"] == "ANOMALOUS":
        anoms.append((4100, w))
if not anoms:
    for w in windows_of(v3, s01):
        if w.get("decision") == "ANOMALOUS":
            anoms.append((4100, w))
reg.add("QA-V3-006", "XAI-001", "ANOMALOUS windows exist to be explained (v3 flags windows rarely by design)", "scan cold high-scale trips + S05", ">= 1 window", f"{len(anoms)} ANOMALOUS windows found (seeds {sorted({a for a, _ in anoms})})",
        "PASS" if anoms else "BLOCKED")
if anoms:
    seed, anom = anoms[0]
    x1, x2 = explain(v3, anom), explain(v3, anom)
    x3 = explain(v3, anoms[-1][1])
    x = np.array(anom["features"]); bg = np.array(md["background"])
    worst = 0.0
    for g, sensors in GROUPS.items():
        ix = group_members(sensors)
        c = x.copy(); c[ix] = bg[ix]
        eff = float(-v3.pipeline.score_samples([x])[0] - (-v3.pipeline.score_samples([c])[0]))
        worst = max(worst, abs(eff - next(e["effect"] for e in x1["effects"] if e["group"] == g)))
    top = max(x1["effects"], key=lambda e: e["effect"])
    refused = []
    for label, win in (("insufficient", {"decision": "INSUFFICIENT_DATA"}), ("other model", {**anom, "model_sha256": "x"}), ("tampered features", {**anom, "features": [0.0] * 47})):
        try:
            explain(v3, win)
            refused.append(f"{label}: EXPLAINED")
        except ValueError:
            pass
    (folder / "xai-v3.json").write_text(json.dumps({"window": {k: anom[k] for k in ("start_ms", "end_ms", "score", "threshold")}, "effects": x1["effects"], "refused_all": not refused}, indent=2, default=str), encoding="utf8")
    reg.check("QA-V3-007", "XAI-001/002", "XAI for v3: deterministic, equals an independent recomputation from the pipeline, bound to the model SHA, strongest group raises the score",
              "explain ANOMALOUS window twice + another, recompute counterfactuals", "identical; |diff| < 1e-12; sha matches v3; top effect > 0",
              x1["effects"] == x2["effects"] and worst < 1e-12 and x1["model_sha256"] == md["sha256"] and top["effect"] > 0 and x1["effects"] != x3["effects"],
              f"max_independent_diff={worst:.2e} top_group={top['group']} effect={top['effect']:.4f} window_end={x1['end_ms']} score={anom['score']:.3f} thr={anom['threshold']:.3f}", rel(folder / "xai-v3.json"))
    reg.check("QA-V3-008", "XAI-001", "XAI refuses insufficient data, another model's result and tampered features", "three invalid inputs", "ValueError each", not refused, "all refused" if not refused else str(refused))

# the ANOMALOUS-only gate lives in Session (call sites), not in explain(); verify it on stored analyses
import sqlite3  # noqa: E402

# ------------------------------------------------------------------ session level: events, linking, reports AR/EN
def session_events(name, scen, seed=4100):
    p = tmp / f"{name}.sqlite3"
    for f in tmp.glob(f"{name}.sqlite3*"):
        f.unlink()
    src = SimulationSource(seed=seed, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=tuple(scen))
    out = []
    with SQLiteRepository(p) as repo:
        s = Session(src, repo, analyzer=AnomalyAnalyzer(), ml_alerts=False)  # same policy as the application worker
        s.start()
        while not src.exhausted:
            s.step()
        s.stop()
        for r in repo.list_events():
            ev = repo.get_event(r["event_id"])
            analysis, status, later = load_ai_context(repo, ev)
            out.append((ev, analysis, status, later, repo.get_detections(ev.event_id)))
    return out


states = {}
rep_rows = []
stored_dec = {}
for sid in ("S01", "S02", "S03", "S04", "S05", "S06", "S07"):
    for ev, analysis, status, later, dets in session_events(f"e_{sid}", (ScenarioInstance(sid, 60_000, 35_000),)):
        if ev.trigger.kind == "DATA_QUALITY":
            continue
        rep = build_report_model(ev, analysis, dets, status, later)
        ar, en = render_simple(rep, "ar"), render_simple(rep, "en")
        tar, ten = render_technical(rep, "ar"), render_technical(rep, "en")
        (folder / "reports" / f"{sid}-{ev.trigger.kind}-simple-ar.txt").write_text(ar, encoding="utf8")
        (folder / "reports" / f"{sid}-{ev.trigger.kind}-simple-en.txt").write_text(en, encoding="utf8")
        (folder / "reports" / f"{sid}-{ev.trigger.kind}-technical-ar.txt").write_text(tar, encoding="utf8")
        (folder / "reports" / f"{sid}-{ev.trigger.kind}-technical-en.txt").write_text(ten, encoding="utf8")
        state = status["state"] if status else None
        states[f"{sid}:{ev.trigger.kind}"] = state
        rep_rows.append({"scenario": sid, "kind": ev.trigger.kind, "ai_state": state, "ar_len": len(ar), "en_len": len(en), "en_arabic_chars": len(ARABIC.findall(en)),
                         "ar_has_ai_section": "الذكاء الاصطناعي" in ar, "model_in_technical": md["model_version"] in tar and md["model_version"] in ten,
                         "xai_in_simple": "ليست أسبابًا ميكانيكية" in ar, "analysis_decision": (analysis or {}).get("decision")})
(folder / "report-matrix.json").write_text(json.dumps(rep_rows, indent=2, ensure_ascii=False), encoding="utf8")
ok_rep = bool(rep_rows) and all(r["ar_len"] > 300 and r["en_len"] > 300 and r["ar_has_ai_section"] and r["model_in_technical"] for r in rep_rows)
reg.check("QA-V3-009", "UX/RPT", "Reports for all seven faults exist in Arabic and English (simple + technical) with an AI section and the v3 model version",
          "7 faulted sessions with the real analyzer under the app policy (ml_alerts=False)", "non-empty reports; AI section; v3 version in both technical reports", ok_rep,
          f"{len(rep_rows)} events; states={states}", rel(folder / "report-matrix.json"))
leak = [r for r in rep_rows if r["en_arabic_chars"] > 0]
reg.check("QA-V3-010", "UX/RPT", "English reports contain no Arabic text", "scan the 7 English simple reports", "0 Arabic characters", not leak,
          "none" if not leak else "; ".join(f"{r['scenario']}:{r['en_arabic_chars']}" for r in leak))
# consistency: XAI wording only when the linked analysis is ANOMALOUS
incons = [r for r in rep_rows if (r["analysis_decision"] == "ANOMALOUS") != r["xai_in_simple"]]
reg.check("QA-V3-011", "XAI-003", "Report XAI section appears if and only if the linked analysis is ANOMALOUS (decision/explanation consistency)",
          "compare stored linked decision with the simple report wording", "no mismatch", not incons, f"decisions={[ (r['scenario'], r['analysis_decision']) for r in rep_rows]}; mismatches={incons}")

for f in sorted(tmp.glob("e_S0*.sqlite3")):
    con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
    for (j,) in con.execute("SELECT data_json FROM analyses"):
        a = json.loads(j)
        key = (a.get("decision"), "xai" in a)
        stored_dec[str(key)] = stored_dec.get(str(key), 0) + 1
    con.close()
bad_gate = {k: v for k, v in stored_dec.items() if (k.startswith("('ANOMALOUS'") is False and k.endswith("True)"))}
reg.check("QA-V3-008b", "XAI-001", "Session attaches XAI only to ANOMALOUS analyses (gate verified on every analysis stored by the 7 sessions)", "count stored (decision, has_xai) pairs",
          "no non-ANOMALOUS analysis carries xai", not bad_gate, json.dumps(stored_dec) + f"; violations={bad_gate}",
          notes="explain() itself does not check the decision label (it checks model SHA, schema and score/features consistency); the gate is in Session. Unchanged design since CR-005.")

# linking limits with the real v3 analyzer
an = AnomalyAnalyzer(v3)
for smp in [s for s in normal if s.timestamp_ms <= 68_200]:
    an.push(smp)
sid_ = normal[0].session_id
limits = {"2000 ms old": an.latest_before(sid_, 70_000) is not None, "2001 ms old": an.latest_before(sid_, 70_001) is None, "other session": an.latest_before("zzz", 68_200) is None,
          "future window not returned": an.latest_before(sid_, 67_999)["end_ms"] <= 67_999}
reg.check("QA-V3-012", "INT-003", "Analysis linking: age limit 2000 ms, other session and future windows never linked (real v3 analyzer)", "latest_before at boundary times", "all true", all(limits.values()), json.dumps(limits))
reg.save()
