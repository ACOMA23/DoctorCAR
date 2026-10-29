"""Grouped reference replacement; score effects are not additive SHAP or causation."""

import hashlib
import json
import time
from typing import Any

import numpy as np

from doctorcar.analysis.model import AnomalyModel
from doctorcar.analysis.windows import FEATURE_NAMES

METHOD = "grouped-training-median-perturbation-v2"
EPSILON = 1e-8
GROUPS = {
    "temperature": ("COOLANT_TEMP", "INTAKE_TEMP"),
    "air_fuel_operation": (
        "RPM",
        "ENGINE_LOAD",
        "THROTTLE_POS",
        "MAF",
        "INTAKE_PRESSURE",
        "SHORT_FUEL_TRIM",
        "LONG_FUEL_TRIM",
    ),
    "voltage": ("CONTROL_MODULE_VOLTAGE",),
    "speed": ("SPEED",),
}
GROUP_NAMES = {
    "temperature": ("تغير الحرارة", "Temperature behavior"),
    "air_fuel_operation": (
        "علاقات الهواء والوقود وظروف التشغيل",
        "Air/fuel and operating relationships",
    ),
    "voltage": ("جهد التغذية", "Supply voltage"),
    "speed": ("سرعة المركبة", "Vehicle speed"),
}


def group_members(sensors: tuple[str, ...]) -> list[int]:
    return [i for i, n in enumerate(FEATURE_NAMES) if n.split(".")[0] in sensors]


def direction(effect: float) -> str:
    """raises/lowers refer to the model's anomaly score, never to a mechanical condition."""
    return "raises_score" if effect > EPSILON else "lowers_score" if effect < -EPSILON else "none"


def explain(model: AnomalyModel, result: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    if (
        result.get("model_sha256") != model.metadata["sha256"]
        or result.get("feature_names") != list(FEATURE_NAMES)
        or "score" not in result
    ):
        raise ValueError("Explanation requires the exact scored model and feature schema")
    x = np.array(result["features"], dtype=float)
    background = np.array(model.metadata["background"], dtype=float)
    original = float(model.scores([x])[0])
    if not np.isclose(original, result["score"], atol=1e-12, rtol=0):
        raise ValueError("Stored score does not match stored features")
    used = set(model.metadata.get("selected_feature_indices", range(len(FEATURE_NAMES))))
    rows, indices = [], []
    for sensors in GROUPS.values():
        ix = group_members(sensors)
        changed = x.copy()
        changed[ix] = background[ix]
        rows.append(changed)
        indices.append(ix)
    replacement_scores = model.scores(rows)
    effects: list[dict[str, Any]] = [
        {
            "group": name,
            "feature_indices": ix,
            "replacement_score": float(score),
            "effect": original - float(score),
            "direction": direction(original - float(score)),
            # A zero effect from a group the model never reads is a design fact, not evidence.
            "used_by_model": any(i in used for i in ix),
        }
        for name, ix, score in zip(GROUPS, indices, replacement_scores, strict=True)
    ]
    effects.sort(key=lambda e: abs(e["effect"]), reverse=True)
    # Single-feature replacement for the features the model actually reads.
    single = []
    for i in sorted(used):
        changed = x.copy()
        changed[i] = background[i]
        single.append(changed)
    single_scores = model.scores(single) if single else []
    features: list[dict[str, Any]] = [
        {
            "name": FEATURE_NAMES[i],
            "index": i,
            "value": float(x[i]),
            "reference": float(background[i]),
            "relation_to_reference": "above" if x[i] > background[i] else "below",
            "effect": original - float(score),
            "direction": direction(original - float(score)),
        }
        for i, score in zip(sorted(used), single_scores, strict=True)
    ]
    features.sort(key=lambda e: abs(e["effect"]), reverse=True)
    identity = json.dumps(
        [result["session_id"], result["end_ms"], model.metadata["sha256"], x.tolist()]
    )
    return {
        "status": "AVAILABLE",
        "method": METHOD,
        "analysis_run_id": hashlib.sha256(identity.encode()).hexdigest(),
        "model_version": result["model_version"],
        "model_sha256": model.metadata["sha256"],
        "decision": result.get("decision"),
        "threshold": result.get("threshold"),
        "start_ms": result["start_ms"],
        "end_ms": result["end_ms"],
        "original_score": original,
        "effects": effects,
        "feature_effects": features[:8],
        "reference": "Per-feature medians of training windows only",
        "reference_values": background.tolist(),
        "limitations": (
            "Non-additive effects; correlated groups and median reference may be "
            "physically unrealistic. Not mechanical causation or probabilities."
        ),
        "elapsed_ms": (time.perf_counter() - started) * 1000,
    }
