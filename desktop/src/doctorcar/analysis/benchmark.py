"""DC-CR-005 offline pipeline: independent trip sets, event-level calibration and evaluation.

Ground truth (scenario schedules) is used only to build splits, labels and scoring. It is never
an input to inference, training features or the application's decisions.
"""

import argparse
import hashlib
import json
import random
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from doctorcar.analysis.analyzer import DetectionPolicy, PersistenceGate
from doctorcar.analysis.model import MODEL_V1, MODEL_V2, MODELS_ROOT, AnomalyModel
from doctorcar.analysis.windows import FEATURE_NAMES, SCHEMA_VERSION, WindowBuilder, WindowConfig
from doctorcar.core.sensor_registry import NUMERIC_IDS
from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.monitoring.event_detector import EventDetector
from doctorcar.sources.scenarios import ScenarioInstance, validate_scenarios
from doctorcar.sources.simulation import SimulationSource

DATASET_V2 = Path("data/cr005-dataset")
DATASET_V2_VERSION = "dataset-3"
GENERATOR_V2 = "correlated-model-1-diverse-trips-2"
MATCH_GRACE_MS = 10_000  # an alarm up to 10 s after the injection ended still matches it
REFRACTORY_MS = 30_000  # same-source alarms inside the recorder's 30 s event are one event
NEARBY_MS = 10_000  # Session merges rule and ML detections within 10 s into one event
HYSTERESIS = 0.02
PERSISTENCE_GRID = (2, 3, 4, 5)
FALSE_ALARM_BUDGET = 0  # validation false-alarm events allowed during threshold calibration
TRIP_SECONDS = 155
RELATIONS = ("MAF.relative_residual", "INTAKE_PRESSURE.residual", "RPM.trim_correlation")
V1_SELECTED = (
    "COOLANT_TEMP.mean",
    "COOLANT_TEMP.slope",
    "SHORT_FUEL_TRIM.mean",
    "SHORT_FUEL_TRIM.std",
    "LONG_FUEL_TRIM.mean",
    "CONTROL_MODULE_VOLTAGE.mean",
    "CONTROL_MODULE_VOLTAGE.std",
    *RELATIONS[:2],
    RELATIONS[2],
    "MAF.coverage",
    "INTAKE_PRESSURE.coverage",
)
CANDIDATE_SETS: dict[str, tuple[str, ...]] = {
    "selected-12": V1_SELECTED,
    "means-slopes-relations-25": tuple(
        f"{s}.{stat}" for s in NUMERIC_IDS for stat in ("mean", "slope")
    )
    + RELATIONS,
    "all-47": tuple(FEATURE_NAMES),
}


@dataclass(frozen=True)
class TripSpec:
    trip: str
    split: str
    seed: int
    scale: float
    warm: bool
    scenarios: tuple[ScenarioInstance, ...] = ()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf8"
    )


def trip_plan() -> list[TripSpec]:
    """Deterministic, disjoint trip sets. Seeds never repeat across splits."""
    rng = random.Random(20261028)
    plan: list[TripSpec] = []

    def add(split: str, base: int, warm: bool, scenarios: tuple[ScenarioInstance, ...]) -> None:
        validate_scenarios(scenarios)
        seed = base + len(plan)
        scale = round(rng.uniform(0.85, 1.15), 4)
        plan.append(TripSpec(f"{split}-{seed}", split, seed, scale, warm, scenarios))

    def normal(split: str, base: int, count: int) -> None:
        for i in range(count):
            add(split, base, i % 2 == 1, ())

    def single(sid: str, variant: str = "default") -> tuple[ScenarioInstance, ...]:
        return (
            ScenarioInstance(
                sid,
                rng.choice(range(45000, 85001, 5000)),
                rng.choice((15000, 25000, 35000)),
                rng.choice((0.7, 0.85, 1.0)),
                variant,
            ),
        )

    def faulty(split: str, base: int, groups: list[tuple[ScenarioInstance, ...]]) -> None:
        for scenarios in groups:
            add(split, base, rng.random() < 0.5, scenarios)

    ids = [f"S0{i}" for i in range(1, 8)]
    combos: list[tuple[ScenarioInstance, ...]] = [
        (ScenarioInstance("S01", 40000, 45000), ScenarioInstance("S02", 60000, 35000)),
        (ScenarioInstance("S03", 50000, 30000), ScenarioInstance("S06", 80000, 30000)),
    ]
    normal("train", 5000, 60)
    normal("validation", 6000, 18)
    validation = [single(s) for s in ids for _ in range(2)]
    validation += [single("S07", v) for v in ("flatline", "implausible")]
    faulty("validation", 6000, validation + combos)
    normal("test", 7000, 30)
    test = [single(s) for s in ids for _ in range(4)]
    test += [single("S07", v) for v in ("flatline", "implausible", "flatline", "implausible")]
    test_combos: list[tuple[ScenarioInstance, ...]] = combos + [
        (ScenarioInstance("S04", 45000, 30000), ScenarioInstance("S05", 85000, 25000)),
        (ScenarioInstance("S06", 50000, 20000), ScenarioInstance("S06", 100000, 20000)),
    ]
    faulty("test", 7000, test + test_combos)
    return plan


def trip_plan_v3() -> list[TripSpec]:
    """DC-FIX-001 plan: new seed ranges (12000+), more and stratified normal trips.

    Disjoint from every seed used by DC-CR-005 (5000-7199) and by the DC-QA-001 campaign
    (9000-9199). Normal trips cover cold/warm starts evenly across the whole driving-scale range
    (DEF-002: the previous plan under-covered cold starts at high scale).
    """
    rng = random.Random(20261029)
    plan: list[TripSpec] = []

    def add(
        split: str,
        base: int,
        warm: bool,
        scenarios: tuple[ScenarioInstance, ...],
        scale: float | None = None,
    ) -> None:
        validate_scenarios(scenarios)
        seed = base + len(plan)
        plan.append(
            TripSpec(
                f"{split}-{seed}",
                split,
                seed,
                scale if scale is not None else round(rng.uniform(0.85, 1.15), 4),
                warm,
                scenarios,
            )
        )

    def normal(split: str, base: int, count: int) -> None:
        scales = [round(0.85 + 0.30 * (i + 0.5) / count, 4) for i in range(count)]
        rng.shuffle(scales)
        for i in range(count):
            add(split, base, i % 2 == 1, (), scales[i])

    def single(sid: str, variant: str = "default") -> tuple[ScenarioInstance, ...]:
        return (
            ScenarioInstance(
                sid,
                rng.choice(range(45000, 85001, 5000)),
                rng.choice((15000, 25000, 35000)),
                rng.choice((0.7, 0.85, 1.0)),
                variant,
            ),
        )

    def faulty(split: str, base: int, groups: list[tuple[ScenarioInstance, ...]]) -> None:
        for scenarios in groups:
            add(split, base, rng.random() < 0.5, scenarios)

    ids = [f"S0{i}" for i in range(1, 8)]
    combos: list[tuple[ScenarioInstance, ...]] = [
        (ScenarioInstance("S01", 40000, 45000), ScenarioInstance("S02", 60000, 35000)),
        (ScenarioInstance("S03", 50000, 30000), ScenarioInstance("S06", 80000, 30000)),
    ]
    normal("train", 12000, 120)
    normal("validation", 13000, 60)
    validation = [single(s) for s in ids for _ in range(2)]
    validation += [single("S07", v) for v in ("flatline", "implausible")]
    faulty("validation", 13000, validation + combos)
    normal("test", 14000, 40)
    test = [single(s) for s in ids for _ in range(4)]
    test += [single("S07", v) for v in ("flatline", "implausible", "flatline", "implausible")]
    test_combos: list[tuple[ScenarioInstance, ...]] = combos + [
        (ScenarioInstance("S04", 45000, 30000), ScenarioInstance("S05", 85000, 25000)),
        (ScenarioInstance("S06", 50000, 20000), ScenarioInstance("S06", 100000, 20000)),
    ]
    faulty("test", 14000, test + test_combos)
    return plan


PLANS = {"cr005": trip_plan, "cr006": trip_plan_v3}


def stream_trip(spec: TripSpec) -> Iterator[Any]:
    """Yield accepted validation results exactly as Session would feed the detectors."""
    source = SimulationSource(
        seed=spec.seed,
        scenario_family="multisensor",
        mode="FAULT_INJECTION" if spec.scenarios else "NORMAL",
        scenarios=spec.scenarios,
        driving_scale=spec.scale,
        warm_start=spec.warm,
    )
    source.connect()
    source.session_id = spec.trip
    source.start()
    validator = DataQualityValidator()
    try:
        while (sample := source.read_measurements()) is not None:
            result = validator.validate_measurement(replace(sample, received_at_ms=None))
            if result.accepted:
                yield result
    finally:
        source.disconnect()


def fault_active(spec: TripSpec, end_ms: int) -> bool:
    return any(s.start_ms <= end_ms < s.start_ms + s.duration_ms for s in spec.scenarios)


def load_specs(root: Path = DATASET_V2) -> tuple[dict[str, Any], list[TripSpec]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf8"))
    specs = [
        TripSpec(
            t["trip"],
            t["split"],
            t["seed"],
            t["driving_scale"],
            t["warm_start"],
            tuple(ScenarioInstance(**s) for s in t["scenarios"]),
        )
        for t in manifest["trips"]
    ]
    return manifest, specs


def generate(root: Path = DATASET_V2, plan_name: str = "cr005") -> dict[str, Any]:
    if (root / "manifest.json").exists():
        raise FileExistsError(f"{root} already holds a dataset; refusing to overwrite it")
    root.mkdir(parents=True, exist_ok=True)
    plan = PLANS[plan_name]()
    assert len({s.seed for s in plan}) == len(plan) and len({s.trip for s in plan}) == len(plan)
    features: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    trips: list[dict[str, Any]] = []
    for spec in plan:
        builder, count, windows = WindowBuilder(), 0, 0
        digest = hashlib.sha256()
        for result in stream_trip(spec):
            count += 1
            window = builder.push(result.sample)
            if window is None:
                continue
            at = window["end_ms"]
            ready = window["decision"] == "READY"
            labels.append(
                {
                    "trip": spec.trip,
                    "end_ms": at,
                    "fault_active": fault_active(spec, at),
                    "split": spec.split,
                    "valid": ready,
                }
            )
            if ready:
                row = dict(zip(FEATURE_NAMES, window["features"], strict=True))
                features.append({"trip": spec.trip, "end_ms": at, "split": spec.split, **row})
                digest.update(np.asarray(window["features"], dtype=float).tobytes())
                windows += 1
        trips.append(
            {
                "trip": spec.trip,
                "split": spec.split,
                "seed": spec.seed,
                "driving_scale": spec.scale,
                "warm_start": spec.warm,
                "scenarios": [asdict(s) for s in spec.scenarios],
                "sample_count": count,
                "window_count": windows,
                "features_sha256": digest.hexdigest(),
            }
        )
    pd.DataFrame(features).to_csv(root / "features.csv", index=False)
    pd.DataFrame(labels).to_csv(root / "labels.csv", index=False)
    counts = {
        split: {
            "normal": sum(1 for t in trips if t["split"] == split and not t["scenarios"]),
            "fault": sum(1 for t in trips if t["split"] == split and t["scenarios"]),
        }
        for split in ("train", "validation", "test")
    }
    manifest = {
        "version": DATASET_V2_VERSION if plan_name == "cr005" else f"dataset-{plan_name}",
        "generator_version": GENERATOR_V2,
        "trip_plan": plan_name,
        "feature_schema": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "window": asdict(WindowConfig()),
        "counts": counts,
        "label_source": "Injected schedule held separately; scoring only, not mechanical faults",
        "match_rule": {
            "truth_window": "[start_ms, start_ms + duration_ms + grace_ms]",
            "grace_ms": MATCH_GRACE_MS,
            "refractory_ms": REFRACTORY_MS,
            "merge_nearby_ms": NEARBY_MS,
        },
        "trips": trips,
        "limitations": [
            "Same synthetic generator in every split; distinct seeds and driving scales do not "
            "prove vehicle generalization",
            "Trip timeline is fixed (cold/warm start, idle, accelerate, cruise, shutdown)",
            "No DTC or ECU Freeze Frame generated; no real vehicle data",
        ],
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def gate_alarms(
    rows: list[tuple[int, float | None]], threshold: float, policy: DetectionPolicy
) -> list[int]:
    gate = PersistenceGate(threshold, policy)
    return [end for end, score in rows if gate.update(score)]


def match_alarms(spec: TripSpec, alarms: list[list[int]]) -> dict[str, Any]:
    """Each alarm is a group of detection times (one entry unless rule and ML were merged).

    A group matches an injection when any member falls in [start, end + grace]; it is a false
    alarm only when no member does, so a merged event is not lost to its earliest member.
    """
    spans = [(s, s.start_ms, s.start_ms + s.duration_ms + MATCH_GRACE_MS) for s in spec.scenarios]
    events = []
    for scenario, begin, end in spans:
        hits = sorted(a for group in alarms for a in group if begin <= a <= end)
        events.append(
            {
                "trip": spec.trip,
                "scenario": scenario.scenario_id,
                "variant": scenario.variant,
                "start_ms": scenario.start_ms,
                "duration_ms": scenario.duration_ms,
                "severity": scenario.severity,
                "detected": bool(hits),
                "delay_ms": hits[0] - scenario.start_ms if hits else None,
            }
        )
    false_alarms = [
        group[0] for group in alarms if not any(b <= a <= e for a in group for _, b, e in spans)
    ]
    return {"events": events, "false_alarms": false_alarms, "alarms": len(alarms)}


def summarize(matches: list[dict[str, Any]], specs: list[TripSpec]) -> dict[str, Any]:
    events = [e for m in matches for e in m["events"]]
    detected = [e for e in events if e["detected"]]
    alarms = sum(m["alarms"] for m in matches)
    false_alarms = sum(len(m["false_alarms"]) for m in matches)
    normal_fa = sum(
        len(m["false_alarms"]) for m, s in zip(matches, specs, strict=True) if not s.scenarios
    )
    normal_trips = sum(1 for s in specs if not s.scenarios)
    hours = len(specs) * TRIP_SECONDS / 3600
    normal_hours = normal_trips * TRIP_SECONDS / 3600
    delays = sorted(e["delay_ms"] / 1000 for e in detected)
    return {
        "truth_events": len(events),
        "detected_events": len(detected),
        "missed_events": len(events) - len(detected),
        "recall": len(detected) / len(events) if events else 0.0,
        "alarm_events": alarms,
        "true_alarm_events": alarms - false_alarms,
        "false_alarm_events": false_alarms,
        "precision": (alarms - false_alarms) / alarms if alarms else 0.0,
        "false_alarms_per_simulated_hour": false_alarms / hours,
        "false_alarm_events_on_normal_trips": normal_fa,
        "normal_trips": normal_trips,
        "false_alarms_per_normal_hour": normal_fa / normal_hours if normal_hours else 0.0,
        "simulated_hours": hours,
        "detection_delay_s_median": delays[len(delays) // 2] if delays else None,
        "detection_delay_s_mean": float(np.mean(delays)) if delays else None,
    }


def window_metrics(y: Any, p: Any, hours: float) -> dict[str, Any]:
    tp, fp = int(np.sum(y & p)), int(np.sum(~y & p))
    fn, tn = int(np.sum(y & ~p)), int(np.sum(~y & ~p))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_positive_windows_per_simulated_hour": fp / hours,
        "confusion_matrix_actual_rows_predicted_columns": [[tn, fp], [fn, tp]],
    }


def make_pipeline_v2(columns: list[int]) -> Any:
    return make_pipeline(
        ColumnTransformer([("selected", "passthrough", columns)], remainder="drop"),
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        IsolationForest(
            n_estimators=200, max_samples=256, contamination="auto", random_state=505, n_jobs=1
        ),
    )


def train(
    root: Path = DATASET_V2, name: str = MODEL_V2, model_version: str = "iforest-cr005-v2"
) -> dict[str, Any]:
    manifest, specs = load_specs(root)
    by_trip = {s.trip: s for s in specs}
    frame = pd.read_csv(root / "features.csv")
    labels = pd.read_csv(root / "labels.csv")
    train_rows = frame[frame.split == "train"]
    assert not any(by_trip[t].scenarios for t in set(train_rows.trip)), "train must be fault-free"
    assert set(train_rows.trip).isdisjoint(frame[frame.split != "train"].trip)
    validation = frame[frame.split == "validation"].reset_index(drop=True)
    val_specs = [s for s in specs if s.split == "validation"]
    ends = {s.trip: sorted(int(e) for e in labels[labels.trip == s.trip].end_ms) for s in val_specs}
    positions = {(r.trip, int(r.end_ms)): i for i, r in enumerate(validation.itertuples())}
    x_train = train_rows[list(FEATURE_NAMES)].to_numpy()
    x_val = validation[list(FEATURE_NAMES)].to_numpy()
    selection: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for set_name, names in CANDIDATE_SETS.items():
        model = make_pipeline_v2([FEATURE_NAMES.index(n) for n in names])
        model.fit(x_train)
        scores = -model.score_samples(x_val)
        grid = np.unique(np.quantile(scores, np.linspace(0.5, 1, 401)))
        set_best: dict[str, Any] | None = None
        for k in PERSISTENCE_GRID:
            policy = DetectionPolicy(k, HYSTERESIS)
            for threshold in grid:
                matches = []
                for spec in val_specs:
                    rows = [
                        (
                            e,
                            float(scores[positions[(spec.trip, e)]])
                            if (spec.trip, e) in positions
                            else None,
                        )
                        for e in ends[spec.trip]
                    ]
                    alarms = [[a] for a in gate_alarms(rows, float(threshold), policy)]
                    matches.append(match_alarms(spec, alarms))
                summary = summarize(matches, val_specs)
                if summary["false_alarm_events"] > FALSE_ALARM_BUDGET:
                    continue
                key = (
                    summary["recall"],
                    -(summary["detection_delay_s_mean"] or 1e9),
                    -len(names),
                )
                if set_best is None or key > set_best["key"]:
                    set_best = {
                        "key": key,
                        "feature_set": set_name,
                        "names": names,
                        "consecutive": k,
                        "threshold": float(threshold),
                        "grid": grid,
                        "model": model,
                        "recall": summary["recall"],
                        "delay_mean_s": summary["detection_delay_s_mean"],
                    }
        selection.append(
            {
                "feature_set": set_name,
                "features": len(names),
                "best_feasible": None
                if set_best is None
                else {
                    k: set_best[k] for k in ("consecutive", "threshold", "recall", "delay_mean_s")
                },
            }
        )
        if set_best is not None and (best is None or set_best["key"] > best["key"]):
            best = set_best
    if best is None:
        raise RuntimeError("No candidate met the validation false-alarm budget")
    above = best["grid"][best["grid"] > best["threshold"]]
    threshold = float(above[0]) if len(above) else best["threshold"]
    directory = MODELS_ROOT / name
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(best["model"], directory / "model.joblib")
    meta = {
        "model_version": model_version,
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "feature_schema": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "window": asdict(WindowConfig()),
        "threshold": threshold,
        "detection_policy": {"consecutive": best["consecutive"], "hysteresis": HYSTERESIS},
        "threshold_policy": (
            "Lowest threshold on a 401-level validation-score quantile grid whose persistence "
            f"policy gives <= {FALSE_ALARM_BUDGET} validation false-alarm events, maximizing "
            "validation event recall; one grid step above for margin. Test split never used."
        ),
        "feature_set": best["feature_set"],
        "selected_feature_indices": [FEATURE_NAMES.index(n) for n in best["names"]],
        "selection_log": selection,
        "train_trips": sorted(set(train_rows.trip)),
        "validation_trips": sorted(set(validation.trip)),
        "background": np.median(x_train, axis=0).tolist(),
        "training_rows": len(train_rows),
        "hyperparameters": {"n_estimators": 200, "max_samples": 256, "random_state": 505},
        "validation": {"recall_at_selected": best["recall"], "false_alarm_events": 0},
        "dataset_version": manifest["version"],
        "generator_version": manifest["generator_version"],
        "sha256": hashlib.sha256((directory / "model.joblib").read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
    }
    write_json(directory / "metadata.json", meta)
    return meta


def dedupe(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    last: dict[str, int] = {}
    kept = []
    for kind, at in sorted(items, key=lambda i: i[1]):
        if kind not in last or at - last[kind] > REFRACTORY_MS:
            kept.append((kind, at))
            last[kind] = at
    return kept


def combine(rules: list[tuple[str, int]], ml: list[int]) -> list[list[int]]:
    """Mirror Session: non-quality rule and ML detections within 10 s are one event."""
    merged: list[tuple[str, list[int]]] = []
    for kind, at in sorted([*rules, *[("ML", t) for t in ml]], key=lambda i: i[1]):
        target = None
        if kind != "DATA_QUALITY":
            for entry in merged:
                first, other = entry[1][0], entry[0]
                if 0 <= at - first <= NEARBY_MS and (
                    (kind == "ML" and other not in ("ML", "DATA_QUALITY"))
                    or (kind != "ML" and other == "ML")
                ):
                    target = entry
                    break
        if target is None:
            merged.append((kind, [at]))
        else:
            target[1].append(at)
    return [times for _, times in merged]


def evaluate_events(
    models: tuple[str, ...] = (MODEL_V1, MODEL_V2),
    root: Path = DATASET_V2,
    split: str = "test",
) -> dict[str, Any]:
    manifest, all_specs = load_specs(root)
    specs = [s for s in all_specs if s.split == split]
    loaded = {n: AnomalyModel(n) for n in models}
    manifest_sha = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    cache_path = root / f"rules_alarms_{split}.json"
    cached = None
    if cache_path.exists():
        loaded_cache = json.loads(cache_path.read_text(encoding="utf8"))
        if loaded_cache["manifest_sha256"] == manifest_sha:
            cached = {t: [(k, a) for k, a in v] for t, v in loaded_cache["alarms"].items()}
    rules_raw: dict[str, list[tuple[str, int]]] = cached or {}
    ml_raw: dict[str, dict[str, list[int]]] = {n: {} for n in models}
    window_rows: dict[str, list[tuple[bool, bool]]] = {n: [] for n in models}
    for spec in specs:
        detector, builder = EventDetector() if cached is None else None, WindowBuilder()
        gates = {
            n: PersistenceGate(
                float(m.metadata["threshold"]),
                DetectionPolicy(int(m.policy["consecutive"]), float(m.policy["hysteresis"])),
            )
            for n, m in loaded.items()
        }
        if cached is None:
            rules_raw[spec.trip] = []
        for n in models:
            ml_raw[n][spec.trip] = []
        for result in stream_trip(spec):
            if detector is not None:
                for trigger in detector.evaluate_trigger(result.sample, result.issues):
                    rules_raw[spec.trip].append((trigger.kind, trigger.timestamp_ms))
            window = builder.push(result.sample)
            if window is None:
                continue
            for n, m in loaded.items():
                inferred = m.infer(window)
                score = inferred.get("score")
                if gates[n].update(float(score) if score is not None else None):
                    ml_raw[n][spec.trip].append(window["end_ms"])
                if score is not None:
                    window_rows[n].append(
                        (fault_active(spec, window["end_ms"]), inferred["decision"] == "ANOMALOUS")
                    )
    if cached is None:
        write_json(cache_path, {"manifest_sha256": manifest_sha, "alarms": rules_raw})
    rules_events = {t: dedupe(a) for t, a in rules_raw.items()}
    streams: dict[str, dict[str, list[list[int]]]] = {
        "rules": {t: [[at] for _, at in a] for t, a in rules_events.items()}
    }
    for n in models:
        streams[f"ml:{n}"] = {t: [[a] for a in ml_raw[n][t]] for t in ml_raw[n]}
        streams[f"combined:{n}"] = {t: combine(rules_events[t], ml_raw[n][t]) for t in ml_raw[n]}
    matched = {
        label: [match_alarms(s, alarms[s.trip]) for s in specs] for label, alarms in streams.items()
    }
    summaries = {label: summarize(m, specs) for label, m in matched.items()}
    scenarios: dict[str, Any] = {}
    for sid in sorted({e["scenario"] for m in matched["rules"] for e in m["events"]}):
        entry: dict[str, Any] = {}
        for label, per_trip in matched.items():
            rows = [e for m in per_trip for e in m["events"] if e["scenario"] == sid]
            delays = sorted(e["delay_ms"] / 1000 for e in rows if e["detected"])
            entry[label] = {
                "events": len(rows),
                "detected": sum(e["detected"] for e in rows),
                "recall": sum(e["detected"] for e in rows) / len(rows),
                "delay_s_median": delays[len(delays) // 2] if delays else None,
            }
        scenarios[sid] = entry
    windows = {}
    for n in models:
        y = np.array([r[0] for r in window_rows[n]])
        p = np.array([r[1] for r in window_rows[n]])
        windows[n] = window_metrics(y, p, len(y) / 3600)
    result = {
        "split": split,
        "dataset_version": manifest["version"],
        "manifest_sha256": manifest_sha,
        "scoring_note": (
            "Merged rule+ML events match an injection when any member detection falls in its "
            "window (scoring fix applied after the first test run; models and thresholds "
            "unchanged)."
        ),
        "models": {
            n: {
                "version": m.metadata["model_version"],
                "sha256": m.metadata["sha256"],
                "threshold": m.metadata["threshold"],
                "policy": m.policy,
            }
            for n, m in loaded.items()
        },
        "match_rule": manifest["match_rule"],
        "event_level": summaries,
        "window_level": windows,
        "by_scenario": scenarios,
        "false_alarms": {
            label: [
                {"trip": s.trip, "t_s": a / 1000, "normal_trip": not s.scenarios}
                for m, s in zip(per_trip, specs, strict=True)
                for a in m["false_alarms"]
            ]
            for label, per_trip in matched.items()
        },
    }
    write_json(root / f"evaluation_events_{split}.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "train", "evaluate"))
    parser.add_argument("--dataset", type=Path, default=DATASET_V2)
    parser.add_argument("--split", default="test")
    parser.add_argument("--plan", choices=tuple(PLANS), default="cr005")
    parser.add_argument("--model-name", default=MODEL_V2)
    parser.add_argument("--model-version", default="iforest-cr005-v2")
    parser.add_argument("--models", nargs="+", default=[MODEL_V1, MODEL_V2])
    args = parser.parse_args()
    if args.command == "generate":
        value = generate(args.dataset, args.plan)
    elif args.command == "train":
        value = train(args.dataset, args.model_name, args.model_version)
    else:
        value = evaluate_events(tuple(args.models), root=args.dataset, split=args.split)
    print(json.dumps(value, ensure_ascii=True, indent=2)[:6000])


if __name__ == "__main__":
    main()
