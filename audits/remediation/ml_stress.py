"""DC-FIX-001 Gate 5: DEF-002 stress check on fresh fault-free trips (seeds 15000+, never used for
training, validation or threshold selection). Writes docs/evidence/remediation/gate5/ml_stress.json."""

import json
import random
from pathlib import Path

from doctorcar.analysis.analyzer import DetectionPolicy, PersistenceGate
from doctorcar.analysis.benchmark import TripSpec, stream_trip
from doctorcar.analysis.model import AnomalyModel
from doctorcar.analysis.windows import WindowBuilder

OUT = (
    Path(__file__).resolve().parents[2] / "docs" / "evidence" / "remediation" / "gate5"
)
OUT.mkdir(parents=True, exist_ok=True)
MODELS = ("cr004-iforest-v1", "cr005-iforest-v2", "cr006-iforest-v3")
rng = random.Random(20261030)
groups = {
    "cold_high_scale_1.08_1.15": (False, 1.08, 1.15, 15000),
    "cold_mid_scale_0.95_1.05": (False, 0.95, 1.05, 15100),
    "warm_high_scale_1.08_1.15": (True, 1.08, 1.15, 15200),
    "cold_low_scale_0.85_0.92": (False, 0.85, 0.92, 15300),
}
loaded = {n: AnomalyModel(n) for n in MODELS}
report = {}
for label, (warm, lo, hi, base) in groups.items():
    specs = [
        TripSpec(
            f"stress-{base + i}",
            "stress",
            base + i,
            round(rng.uniform(lo, hi), 4),
            warm,
        )
        for i in range(15)
    ]
    stats = {
        n: {
            "alarm_events": 0,
            "trips_with_alarm": 0,
            "anomalous_windows": 0,
            "windows": 0,
        }
        for n in MODELS
    }
    for spec in specs:
        gates = {
            n: PersistenceGate(
                float(m.metadata["threshold"]),
                DetectionPolicy(
                    int(m.policy["consecutive"]), float(m.policy["hysteresis"])
                ),
            )
            for n, m in loaded.items()
        }
        builder, trip_alarm = WindowBuilder(), {n: 0 for n in MODELS}
        for result in stream_trip(spec):
            window = builder.push(result.sample)
            if window is None:
                continue
            for n, m in loaded.items():
                inferred = m.infer(window)
                score = inferred.get("score")
                if score is not None:
                    stats[n]["windows"] += 1
                    stats[n]["anomalous_windows"] += inferred["decision"] == "ANOMALOUS"
                if gates[n].update(float(score) if score is not None else None):
                    trip_alarm[n] += 1
        for n in MODELS:
            stats[n]["alarm_events"] += trip_alarm[n]
            stats[n]["trips_with_alarm"] += trip_alarm[n] > 0
    report[label] = {"trips": len(specs), "models": stats}
(OUT / "ml_stress.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
)
for label, r in report.items():
    print(
        label,
        {n: (v["trips_with_alarm"], v["alarm_events"]) for n, v in r["models"].items()},
    )
