"""Reproducible offline CLI. Ground truth is used only by dataset bookkeeping/evaluation."""

import argparse
import hashlib
import json
from dataclasses import asdict, replace
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

from doctorcar.analysis.model import MODEL_DIR, AnomalyModel
from doctorcar.analysis.windows import FEATURE_NAMES, SCHEMA_VERSION, WindowBuilder, WindowConfig
from doctorcar.core.models import Sample
from doctorcar.monitoring.data_quality import DataQualityValidator
from doctorcar.monitoring.evidence_rules import evaluate_relations
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource

DATASET = Path("data/cr004-dataset")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf8"
    )


def generate(root: Path = DATASET) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    records, labels, trips = [], [], []
    for split, base, normal_count in (
        ("train", 1000, 12),
        ("validation", 2000, 6),
        ("test", 4000, 6),
    ):
        configs: list[tuple[ScenarioInstance, ...]] = [() for _ in range(normal_count)]
        if split != "train":
            configs += [(ScenarioInstance(f"S{i:02}", 60000, 35000, 1),) for i in range(1, 8)]
            configs += [
                (ScenarioInstance("S01", 40000, 45000), ScenarioInstance("S02", 60000, 35000))
            ]
            configs += [
                (ScenarioInstance("S07", 45000, 20000, variant="flatline"),),
                (ScenarioInstance("S07", 65000, 20000, variant="implausible"),),
            ]
        for index, scenarios in enumerate(configs):
            trip_id = f"{split}-{base + index}"
            scale = (0.9, 1.0, 1.1)[index % 3] if not scenarios else 1.0
            warm = index % 2 == 1 if not scenarios else False
            source = SimulationSource(
                seed=base + index,
                scenario_family="multisensor",
                mode="FAULT_INJECTION" if scenarios else "NORMAL",
                scenarios=scenarios,
                driving_scale=scale,
                warm_start=warm,
            )
            source.connect()
            source.session_id = trip_id
            source.start()
            builder, validator = WindowBuilder(), DataQualityValidator()
            sample_count = window_count = 0
            path = root / f"{trip_id}.jsonl"
            with path.open("w", encoding="utf8") as stream:
                while (sample := source.read_measurements()) is not None:
                    sample = replace(sample, received_at_ms=None)
                    normalized = validator.validate_measurement(sample).sample
                    stream.write(json.dumps(sample.to_dict(), ensure_ascii=False) + "\n")
                    sample_count += 1
                    window = builder.push(normalized)
                    if window is None:
                        continue
                    at = window["end_ms"]
                    truth = any(s.start_ms <= at < s.start_ms + s.duration_ms for s in scenarios)
                    labels.append(
                        {
                            "trip": trip_id,
                            "end_ms": at,
                            "fault_active": truth,
                            "split": split,
                            "valid": window["decision"] == "READY",
                        }
                    )
                    if window["decision"] == "READY":
                        records.append(
                            {
                                "trip": trip_id,
                                "end_ms": at,
                                "split": split,
                                **dict(zip(FEATURE_NAMES, window["features"], strict=True)),
                            }
                        )
                        window_count += 1
            source.disconnect()
            trips.append(
                {
                    "trip": trip_id,
                    "seed": base + index,
                    "split": split,
                    "scenarios": [asdict(s) for s in scenarios],
                    "driving_scale": scale,
                    "warm_start": warm,
                    "sample_count": sample_count,
                    "window_count": window_count,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    pd.DataFrame(records).to_csv(root / "features.csv", index=False)
    pd.DataFrame(labels).to_csv(root / "labels.csv", index=False)
    manifest = {
        "version": "dataset-2",
        "generator_version": "correlated-model-1-varied-trips-1",
        "feature_schema": SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "window": asdict(WindowConfig()),
        "trips": trips,
        "label_source": "Injected schedule, held separately; not proven mechanical faults",
        "limitations": [
            "Same toy generator across splits; different seeds do not prove vehicle generalization",
            "Cold/warm and scaled driving only; no real vehicle data",
            "No DTC or ECU Freeze Frame generated",
        ],
    }
    write_json(root / "manifest.json", manifest)
    return manifest


def train(root: Path = DATASET) -> dict[str, Any]:
    frame = pd.read_csv(root / "features.csv")
    truth = pd.read_csv(root / "labels.csv")
    train_rows = frame[frame.split == "train"]
    assert not truth[truth.split == "train"].fault_active.any()
    assert set(train_rows.trip).isdisjoint(frame[frame.split == "test"].trip)
    selected = [
        FEATURE_NAMES.index(n)
        for n in (
            "COOLANT_TEMP.mean",
            "COOLANT_TEMP.slope",
            "SHORT_FUEL_TRIM.mean",
            "SHORT_FUEL_TRIM.std",
            "LONG_FUEL_TRIM.mean",
            "CONTROL_MODULE_VOLTAGE.mean",
            "CONTROL_MODULE_VOLTAGE.std",
            "MAF.relative_residual",
            "INTAKE_PRESSURE.residual",
            "RPM.trim_correlation",
            "MAF.coverage",
            "INTAKE_PRESSURE.coverage",
        )
    ]
    model = make_pipeline(
        ColumnTransformer([("selected", "passthrough", selected)], remainder="drop"),
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        IsolationForest(
            n_estimators=96, max_samples=256, contamination="auto", random_state=404, n_jobs=1
        ),
    )
    model.fit(train_rows[list(FEATURE_NAMES)].to_numpy())
    # Validation-only selection. Initial exploratory test-3000 is retired, not reused.
    validation_all = frame[frame.split == "validation"].merge(
        truth[["trip", "end_ms", "fault_active"]], on=["trip", "end_ms"]
    )
    scores = -model.score_samples(validation_all[list(FEATURE_NAMES)].to_numpy())
    y = validation_all.fault_active.to_numpy(dtype=bool)
    candidates = np.unique(np.quantile(scores, np.linspace(0, 1, 201)))

    def objective(t: float) -> float:
        p = scores > t
        tp, fp, fn = np.sum(y & p), np.sum(~y & p), np.sum(y & ~p)
        return float(2 * tp / (2 * tp + fp + fn)) if tp else 0.0

    threshold = float(max(candidates, key=lambda t: (objective(t), t)))
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_DIR / "model.joblib")
    meta = {
        "model_version": "iforest-cr004-v1",
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "feature_schema": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "window": asdict(WindowConfig()),
        "threshold": threshold,
        "threshold_policy": (
            "maximum validation window F1 on fixed 201 quantile grid; "
            "tie highest threshold; test-3000 exploratory retired"
        ),
        "train_trips": sorted(set(train_rows.trip)),
        "validation_trips": sorted(set(validation_all.trip)),
        "background": np.median(train_rows[list(FEATURE_NAMES)].to_numpy(), axis=0).tolist(),
        "training_rows": len(train_rows),
        "selected_feature_indices": selected,
        "validation_f1": objective(threshold),
        "hyperparameters": {"n_estimators": 96, "max_samples": 256, "random_state": 404},
        "sha256": hashlib.sha256((MODEL_DIR / "model.joblib").read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
    }
    write_json(MODEL_DIR / "metadata.json", meta)
    return meta


def metrics(y: Any, p: Any, hours: float) -> dict[str, Any]:
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


def evaluate(root: Path = DATASET) -> dict[str, Any]:
    model = AnomalyModel()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf8"))
    frame = pd.read_csv(root / "features.csv")
    labels = pd.read_csv(root / "labels.csv")
    test = frame[frame.split == "test"].merge(
        labels[["trip", "end_ms", "fault_active"]], on=["trip", "end_ms"]
    )
    scores = model.scores(test[list(FEATURE_NAMES)].to_numpy())
    predictions = scores > model.metadata["threshold"]
    rule_map = {}
    for trip in (t for t in manifest["trips"] if t["split"] == "test"):
        recent: list[Sample] = []
        validator = DataQualityValidator()
        for line in (root / f"{trip['trip']}.jsonl").read_text(encoding="utf8").splitlines():
            sample = validator.validate_measurement(Sample.from_dict(json.loads(line))).sample
            recent = [s for s in recent if sample.timestamp_ms - s.timestamp_ms <= 8000] + [sample]
            if sample.timestamp_ms % 1000 == 0:
                rule_map[(trip["trip"], sample.timestamp_ms)] = bool(
                    evaluate_relations(tuple(recent))
                )
    rule = np.array([rule_map[(r.trip, r.end_ms)] for r in test.itertuples()])
    y = test.fault_active.to_numpy(dtype=bool)
    hours = len(test) / 3600
    result = {
        "unit": (
            "1-second-stride valid analysis window; active injection labels, "
            "not mechanical diagnosis"
        ),
        "hours_evaluated": hours,
        "windows": len(test),
        "excluded_windows": int(((labels.split == "test") & ~labels.valid).sum()),
        "model_version": model.metadata["model_version"],
        "rules": metrics(y, rule, hours),
        "ml": metrics(y, predictions, hours),
        "combined": metrics(y, rule | predictions, hours),
        "trips": [],
    }
    for trip_id in test.trip.unique():
        mask = (test.trip == trip_id).to_numpy()
        config = next(t for t in manifest["trips"] if t["trip"] == trip_id)
        result["trips"].append(
            {
                "trip": trip_id,
                "scenarios": config["scenarios"],
                "ml": metrics(y[mask], predictions[mask], float(mask.sum()) / 3600),
                "rules": metrics(y[mask], rule[mask], float(mask.sum()) / 3600),
            }
        )
    write_json(root / "evaluation.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "train", "evaluate"))
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()
    value = {"generate": generate, "train": train, "evaluate": evaluate}[args.command](args.dataset)
    print(json.dumps(value, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
