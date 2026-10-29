"""DC-FIX-001 Gate 3: rule coverage, concurrent-fault matrix and healthy-trip false-alarm scan.

Writes only docs/evidence/remediation/gate3/ and a temporary directory; never the user database.
Rules only (no ML), same Session pipeline as the application.
"""

import itertools
import json
import sys
import tempfile
from pathlib import Path

from doctorcar.core.session import Session
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "evidence" / "remediation" / "gate3"
OUT.mkdir(parents=True, exist_ok=True)
EXPECTED = {
    "S01": "MS_THERMAL",
    "S02": "MS_AIR_FUEL",
    "S03": "MS_FUEL_RESPONSE",
    "S04": "MS_AIRFLOW",
    "S05": "MS_SUPPLY",
    "S06": "MS_COMBUSTION",
    "S07": "MS_SIGNAL",
}
tmp = Path(tempfile.mkdtemp(prefix="dc_fix_gate3_"))


def events(source, name):
    for f in tmp.glob(f"{name}.sqlite3*"):
        f.unlink()
    with SQLiteRepository(tmp / f"{name}.sqlite3") as repo:
        session = Session(source, repo)
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        return [
            (r["kind"], r["trigger_ms"] / 1000)
            for r in repo.list_events()
            if r["kind"] != "DATA_QUALITY"
        ]


def fault_run(scenarios, seed=4100):
    return events(
        SimulationSource(
            seed=seed,
            scenario_family="multisensor",
            mode="FAULT_INJECTION",
            scenarios=tuple(scenarios),
        ),
        "f",
    )


report: dict = {}

# 1) healthy trips: no rule event may appear
healthy = {}
for seed in range(8000, 8030):
    healthy[seed] = events(
        SimulationSource(seed=seed, scenario_family="multisensor", mode="NORMAL"), "h"
    )
report["healthy"] = {
    "trips": len(healthy),
    "trips_with_events": sum(1 for v in healthy.values() if v),
    "events": {str(k): v for k, v in healthy.items() if v},
}

# 2) single-fault coverage (same 35 combinations as QA-EVENT-015)
coverage = {}
for sid in EXPECTED:
    for start, dur in (
        (60_000, 5_000),
        (60_000, 9_000),
        (60_000, 35_000),
        (110_000, 35_000),
        (135_000, 15_000),
    ):
        coverage[f"{sid}@{start // 1000}s/{dur // 1000}s"] = fault_run(
            [ScenarioInstance(sid, start, dur)]
        )
report["coverage"] = {
    "detected": sum(1 for v in coverage.values() if v),
    "total": len(coverage),
    "missed": [k for k, v in coverage.items() if not v],
    "detail": coverage,
}

# 3) concurrent matrix: every pair at 60 s / 18 s, plus the S07 flatline variant
matrix = {}
instances = {sid: ScenarioInstance(sid, 60_000, 18_000, 1.0) for sid in EXPECTED}
instances["S07"] = ScenarioInstance("S07", 60_000, 18_000, 0.85, "flatline")
singles = {sid: {k for k, _ in fault_run([inst])} for sid, inst in instances.items()}
report["singles_at_60s_18s"] = {k: sorted(v) for k, v in singles.items()}
for a, b in itertools.combinations(EXPECTED, 2):
    try:
        got = {k for k, _ in fault_run([instances[a], instances[b]])}
    except (
        ValueError
    ) as exc:  # the simulator refuses scenarios that write the same sensor
        matrix[f"{a}+{b}"] = {"not_injectable": str(exc), "kept_both": None, "lost": []}
        continue
    matrix[f"{a}+{b}"] = {
        "events": sorted(got),
        "lost": sorted((singles[a] | singles[b]) - got),
        "kept_both": (singles[a] <= got) and (singles[b] <= got),
    }
report["pairs"] = {
    "total": len(matrix),
    "injectable": sum(1 for v in matrix.values() if v["kept_both"] is not None),
    "kept_both": sum(1 for v in matrix.values() if v["kept_both"]),
    "lost_something": {k: v for k, v in matrix.items() if v["lost"]},
    "detail": matrix,
}

(OUT / "rules_matrix.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
)
print(
    "healthy trips with events:",
    report["healthy"]["trips_with_events"],
    "/",
    report["healthy"]["trips"],
)
print(
    "coverage:",
    report["coverage"]["detected"],
    "/",
    report["coverage"]["total"],
    "missed:",
    report["coverage"]["missed"],
)
print(
    "pairs kept both:",
    report["pairs"]["kept_both"],
    "/",
    report["pairs"]["injectable"],
    "injectable of",
    report["pairs"]["total"],
)
for k, v in report["pairs"]["lost_something"].items():
    print("  lost", k, v["lost"])
sys.exit(0)
