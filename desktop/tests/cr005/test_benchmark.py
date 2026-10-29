"""Gates 2-3: leakage-free splits, shared detection policy, event matching and model loading."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from doctorcar.analysis import model as model_module
from doctorcar.analysis.analyzer import AnomalyAnalyzer, DetectionPolicy, PersistenceGate
from doctorcar.analysis.benchmark import (
    DATASET_V2,
    TripSpec,
    combine,
    load_specs,
    match_alarms,
    trip_plan,
)
from doctorcar.analysis.model import (
    DEFAULT_MODEL,
    MODEL_V1,
    MODEL_V2,
    MODELS_ROOT,
    AnomalyModel,
    ModelLoadError,
)
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource

ROOT = Path(__file__).resolve().parents[3]


def test_persistence_gate_fires_once_latches_and_resets_only_when_clearly_normal():
    gate = PersistenceGate(0.5, DetectionPolicy(3, 0.02))
    fired = [gate.update(s) for s in (0.6, 0.6, None, 0.6, 0.6, 0.6, 0.6, 0.49, 0.6, 0.6, 0.6)]
    assert (
        fired == [False] * 5 + [True] + [False] * 5
    )  # None broke the first run; 0.49 is too close
    assert gate.latched
    for s in (0.4, 0.6, 0.6, 0.6):  # 0.4 < threshold - hysteresis re-arms the gate
        last = gate.update(s)
    assert last is True
    with pytest.raises(ValueError):
        DetectionPolicy(0, 0.02)


def test_application_uses_the_policy_stored_in_the_model_metadata():
    for name in (MODEL_V1, MODEL_V2):
        model = AnomalyModel(name)
        analyzer = AnomalyAnalyzer(model)
        assert analyzer.policy.consecutive == model.policy["consecutive"]
        assert analyzer.gate.threshold == model.metadata["threshold"]
    assert AnomalyModel(MODEL_V1).policy == {"consecutive": 3, "hysteresis": 0.02}
    assert AnomalyModel(MODEL_V2).policy["consecutive"] == 5


def test_event_matching_groups_boundaries_and_false_alarms():
    spec = TripSpec("t", "test", 1, 1.0, False, (ScenarioInstance("S01", 60000, 20000),))
    # window is [60000, 90000]: edges match, outside is a false alarm
    m = match_alarms(spec, [[59999], [60000], [90000], [90001]])
    assert m["events"][0]["detected"] and m["events"][0]["delay_ms"] == 0
    assert m["false_alarms"] == [59999, 90001] and m["alarms"] == 4
    # a merged rule+ML event is not lost because its earliest member precedes the injection
    merged = match_alarms(spec, [[58000, 62000]])
    assert merged["events"][0]["detected"] and merged["false_alarms"] == []
    assert match_alarms(spec, [])["events"][0]["detected"] is False


def test_combine_mirrors_session_merging_of_nearby_rule_and_ml_detections():
    assert combine([("MS_THERMAL", 68000)], [64000]) == [[64000, 68000]]
    assert combine([("MS_THERMAL", 68000)], [57000]) == [[57000], [68000]]  # > 10 s apart
    assert combine([("DATA_QUALITY", 65000)], [64000]) == [[64000], [65000]]  # quality is separate
    assert combine([], [10000, 50000]) == [[10000], [50000]]


def test_dataset_v3_splits_are_disjoint_fault_free_for_training_and_reproducible():
    manifest, specs = load_specs(ROOT / DATASET_V2)
    assert manifest["counts"] == {
        "train": {"normal": 60, "fault": 0},
        "validation": {"normal": 18, "fault": 18},
        "test": {"normal": 30, "fault": 36},
    }
    groups = {s: {t.trip for t in specs if t.split == s} for s in ("train", "validation", "test")}
    seeds = {s: {t.seed for t in specs if t.split == s} for s in groups}
    assert groups["train"].isdisjoint(groups["validation"] | groups["test"])
    assert groups["validation"].isdisjoint(groups["test"])
    assert seeds["train"].isdisjoint(seeds["validation"] | seeds["test"])
    assert seeds["validation"].isdisjoint(seeds["test"])
    assert not any(t.scenarios for t in specs if t.split == "train")
    assert {s.scenario_id for t in specs if t.split == "test" for s in t.scenarios} == {
        f"S0{i}" for i in range(1, 8)
    }
    assert any(t.warm for t in specs if t.split == "train") and not all(
        t.warm for t in specs if t.split == "train"
    )
    assert [t.trip for t in trip_plan()] == [t["trip"] for t in manifest["trips"]]


def test_v2_metadata_records_train_validation_only_and_pins_threshold_policy():
    manifest, _ = load_specs(ROOT / DATASET_V2)
    meta = AnomalyModel(MODEL_V2).metadata
    train = {t["trip"] for t in manifest["trips"] if t["split"] == "train"}
    validation = {t["trip"] for t in manifest["trips"] if t["split"] == "validation"}
    test = {t["trip"] for t in manifest["trips"] if t["split"] == "test"}
    assert set(meta["train_trips"]) == train and set(meta["validation_trips"]) == validation
    assert not (set(meta["train_trips"]) | set(meta["validation_trips"])) & test
    assert (
        meta["manifest_sha256"]
        == hashlib.sha256((ROOT / DATASET_V2 / "manifest.json").read_bytes()).hexdigest()
    )
    assert "Test split never used" in meta["threshold_policy"]
    assert meta["validation"]["false_alarm_events"] == 0 and meta["training_rows"] == 9060
    evaluation = json.loads((ROOT / DATASET_V2 / "evaluation_events_test.json").read_text("utf8"))
    assert evaluation["models"][MODEL_V2]["sha256"] == meta["sha256"]
    assert evaluation["manifest_sha256"] == meta["manifest_sha256"]


def six_original_normal_trips():
    for i in range(6):  # data/cr004-dataset test-4000..4005: the trips that alarmed at 7 s
        yield SimulationSource(
            seed=4000 + i,
            scenario_family="multisensor",
            mode="NORMAL",
            driving_scale=(0.9, 1.0, 1.1)[i % 3],
            warm_start=i % 2 == 1,
        )


def ml_triggers(model_name):
    triggers = []
    for source in six_original_normal_trips():
        source.connect()
        source.start()
        analyzer = AnomalyAnalyzer(AnomalyModel(model_name))
        while (sample := source.read_measurements()) is not None:
            _, trigger = analyzer.push(sample)
            if trigger:
                triggers.append(trigger.timestamp_ms)
        source.disconnect()
    return triggers


def test_deterministic_cold_start_false_alarm_is_gone_in_v2_and_documented_in_v1():
    v1, v2 = ml_triggers(MODEL_V1), ml_triggers(MODEL_V2)
    assert len(v1) >= 6 and any(t <= 10000 for t in v1)  # the audited defect near 7 s
    assert v2 == []  # no alarm during cold start, warm-up or shutdown on those six trips


def test_default_model_is_v3_and_v1_is_preserved_byte_identical():
    assert DEFAULT_MODEL == "cr006-iforest-v3"  # DC-FIX-001 changed the default from v2
    archived = ROOT / "desktop" / "models" / MODEL_V1
    for name in ("model.joblib", "metadata.json"):
        assert (archived / name).read_bytes() == (MODELS_ROOT / MODEL_V1 / name).read_bytes()


def test_model_loading_fails_with_specific_reasons(tmp_path, monkeypatch):
    with pytest.raises(ModelLoadError, match="Unknown model"):
        AnomalyModel("../outside")
    copy = tmp_path / "models"
    shutil.copytree(MODELS_ROOT / MODEL_V2, copy / MODEL_V2)
    monkeypatch.setattr(model_module, "MODELS_ROOT", copy)
    AnomalyModel(MODEL_V2)  # an untouched copy still loads
    meta_path = copy / MODEL_V2 / "metadata.json"
    meta = json.loads(meta_path.read_text("utf8"))
    meta["sha256"] = "0" * 64  # edited metadata no longer matches the artifact
    meta_path.write_text(json.dumps(meta), encoding="utf8")
    with pytest.raises(ModelLoadError, match="integrity"):
        AnomalyModel(MODEL_V2)
    # replacing artifact and metadata together still fails against the pinned hash
    (copy / MODEL_V2 / "model.joblib").write_bytes(b"not the pinned model")
    meta["sha256"] = hashlib.sha256(b"not the pinned model").hexdigest()
    meta_path.write_text(json.dumps(meta), encoding="utf8")
    with pytest.raises(ModelLoadError, match="integrity"):
        AnomalyModel(MODEL_V2)
    shutil.copy(MODELS_ROOT / MODEL_V2 / "model.joblib", copy / MODEL_V2 / "model.joblib")
    shutil.copy(MODELS_ROOT / MODEL_V2 / "metadata.json", meta_path)
    import sklearn

    monkeypatch.setattr(sklearn, "__version__", "0.0.1")
    with pytest.raises(ModelLoadError, match="trained with"):
        AnomalyModel(MODEL_V2)
