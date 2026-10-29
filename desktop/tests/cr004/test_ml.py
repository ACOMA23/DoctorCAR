import json
from dataclasses import replace

import numpy as np
import pytest

from doctorcar.analysis.experiment import DATASET
from doctorcar.analysis.model import MODEL_V1, AnomalyModel
from doctorcar.analysis.windows import FEATURE_NAMES, WindowBuilder, extract
from doctorcar.core.models import Quality, Reading
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource


def stream(scenarios=(), seed=8801):
    source = SimulationSource(
        seed=seed,
        scenario_family="multisensor",
        mode="FAULT_INJECTION" if scenarios else "NORMAL",
        scenarios=scenarios,
    )
    source.connect()
    source.start()
    result = []
    while (s := source.read_measurements()) is not None:
        result.append(s)
    source.disconnect()
    return result


def test_artifact_real_inference_repeatability_variation_and_no_label_input():
    model, other = AnomalyModel(), AnomalyModel()
    normal = stream()[350:376]
    faulty = stream((ScenarioInstance("S01"),))[350:376]
    a, b = model.infer(extract(tuple(normal))), model.infer(extract(tuple(faulty)))
    assert a["score"] != b["score"]
    assert b["score"] > a["score"]
    assert b["score"] == other.infer(extract(tuple(faulty)))["score"]
    renamed = tuple(
        replace(s, phase="S01", raw={"answer": "fault"}, provenance="expected-fault")
        for s in normal
    )
    assert model.infer(extract(renamed))["score"] == a["score"]
    assert a["feature_names"] == list(FEATURE_NAMES)
    assert len(set(model.scores([a["features"], b["features"]]))) == 2


@pytest.mark.parametrize(
    "quality", [Quality.MISSING, Quality.UNSUPPORTED, Quality.STALE, Quality.INVALID]
)
def test_missing_unsupported_stale_are_not_normal_or_zero(quality):
    samples = stream()[:26]
    for s in samples:
        s.readings["MAF"] = Reading(None if quality == Quality.MISSING else 1, "g/s", quality)
    result = AnomalyModel().infer(extract(tuple(samples)))
    assert result["decision"] == "INSUFFICIENT_DATA"
    assert "score" not in result


def test_causal_windows_session_sequence_time_and_units():
    samples = stream()[:26]
    assert extract(tuple(samples))["decision"] == "READY"
    assert extract(tuple(samples[:-1]))["decision"] == "INSUFFICIENT_DATA"
    assert extract(tuple(samples[:10] + samples[11:]))["reason"] == "time/session/sequence_gap"
    builder = WindowBuilder()
    for s in samples:
        last = builder.push(s)
    assert last["end_ms"] == samples[-1].timestamp_ms
    assert builder.push(replace(samples[-1], session_id="other"))["decision"] == "INSUFFICIENT_DATA"
    samples[0].readings["MAF"] = Reading(99, "wrong")
    # One missing row is omitted and reported, never replaced by the invalid value.
    result = extract(tuple(samples))
    assert result["coverage"]["MAF"] == 25 / 26
    assert np.isfinite(result["features"]).all()


def test_trip_split_manifest_and_training_only_preprocessing():
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf8"))
    groups = {
        split: {t["trip"] for t in manifest["trips"] if t["split"] == split}
        for split in ("train", "validation", "test")
    }
    assert len(groups["train"]) == 12 and len(groups["validation"]) == len(groups["test"]) == 16
    assert groups["train"].isdisjoint(groups["test"] | groups["validation"])
    assert groups["test"].isdisjoint(groups["validation"])
    model = AnomalyModel(MODEL_V1)
    assert set(model.metadata["train_trips"]) == groups["train"]
    assert set(model.metadata["validation_trips"]) <= groups["validation"]
    assert model.pipeline.steps[-1][1].n_estimators == 96
    assert model.pipeline.steps[2][1].n_samples_seen_ == model.metadata["training_rows"]
    assert all(not t["scenarios"] for t in manifest["trips"] if t["split"] == "train")
