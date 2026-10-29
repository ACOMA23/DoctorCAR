"""QA-SIM-038 / QA-E2E-005b: masking between simultaneous faults and explanation of every miss in the random run."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402

from doctorcar.core.session import Session  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("gate10b")
folder = EVIDENCE / "gate10b"
folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("masking")


def events(sc, name="p"):
    for f in tmp.glob(f"{name}.sqlite3*"):
        f.unlink()
    src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=tuple(sc))
    with SQLiteRepository(tmp / f"{name}.sqlite3") as repo:
        s = Session(src, repo)
        s.start()
        while not src.exhausted:
            s.step()
        s.stop()
        return [(r["kind"], r["trigger_ms"] / 1000) for r in repo.list_events() if r["kind"] != "DATA_QUALITY"]


s04 = ScenarioInstance("S04", 60000, 18000, 1.0)
s07 = ScenarioInstance("S07", 60000, 18000, 0.85, "flatline")
res = {"S04 alone": events([s04]), "S07 flatline alone": events([s07]), "S04 + S07 flatline together": events([s04, s07]),
       "S04 + S07 dropout (5 s at 120 s) together": events([ScenarioInstance("S04", 90000, 45000, 1.0), ScenarioInstance("S07", 120000, 5000, 0.6, "dropout")]),
       "S07 dropout alone": events([ScenarioInstance("S07", 120000, 5000, 0.6, "dropout")])}
(folder / "masking.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf8")
masked = bool(res["S04 alone"]) and not res["S04 + S07 flatline together"]
reg.check("QA-SIM-038", "MS-RULE/INT-002", "A detectable fault stays detectable when a second, simultaneous fault is present", "S04 alone vs S04 + S07 (flatline) at 60 s",
          "S04 is still detected in the combination", not masked, json.dumps(res, ensure_ascii=False), rel(folder / "masking.json"),
          notes="Rules require a valid reference (MAP); S07 flatline on INTAKE_PRESSURE invalidates it, so the S04 pattern is not reported and nothing explains why.")
same_kind = {}
for second in (120000, 120200, 121000, 125000):
    same_kind[f"S07 dropout at 90 s and again at {second / 1000:.1f} s"] = events([ScenarioInstance("S07", 90000, 5000, 0.85, "dropout"), ScenarioInstance("S07", second, 5000, 0.85, "dropout")])
(folder / "same-kind-boundary.json").write_text(json.dumps(same_kind, ensure_ascii=False, indent=2), encoding="utf8")
counts = {k: sum(1 for e in v if e[0] == "MS_SIGNAL") for k, v in same_kind.items()}
reg.check("QA-EVENT-016", "FR-005", "A second fault of the same kind starting right after the first event's T+30 boundary gets its own event", "S07 dropout at 90 s then again at 120.0/120.2/121/125 s",
          "each of the two faults produces its own MS_SIGNAL event", all(c == 2 for c in counts.values()), json.dumps(counts, ensure_ascii=False), rel(folder / "same-kind-boundary.json"),
          notes="The recorder keeps the first trigger of a kind while an event of that kind is active (window inclusive of T+30), so a new same-kind trigger inside it is dropped; this affects back-to-back 30 s cycles.")
e5 = json.loads((EVIDENCE / "gate10" / "e2e05.json").read_text("utf8"))
reasons = []
for row in e5["comparison"]:
    if row["detected"]:
        continue
    sid, st, dur = row["scenario"], row["start_s"], row["duration_s"]
    if st >= 145:
        why = "engine already stopped (driving profile ends at ~145 s) - simulator limitation"
    elif dur <= 5 and sid == "S01":
        why = "5 s thermal fault too short for the rule (needs sustained rise)"
    elif sid == "S07" and st == 60:
        why = "flatline variant is a known undetected pattern"
    elif sid == "S04" and st == 60:
        why = "masked by the simultaneous S07 flatline (QA-SIM-038)"
    elif sid == "S07" and st == 120:
        why = "swallowed: an MS_SIGNAL event from the S07 at 90 s was still active at 120.0 s (QA-EVENT-016)"
    else:
        why = "unexplained"
    reasons.append({**row, "reason": why})
(folder / "random-run-misses.json").write_text(json.dumps(reasons, ensure_ascii=False, indent=2), encoding="utf8")
reg.check("QA-E2E-005b", "MS-RULE", "Every missed injection in the app's RANDOM_FAULTS run has an identified cause", "classify the 5 misses of QA-E2E-005", "no 'unexplained' miss",
          all(r["reason"] != "unexplained" for r in reasons), "; ".join(f"{r['scenario']}@{r['start_s']:.0f}s/{r['duration_s']:.0f}s: {r['reason']}" for r in reasons), rel(folder / "random-run-misses.json"))
reg.save()
