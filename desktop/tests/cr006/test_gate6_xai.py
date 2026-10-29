"""DC-FIX-001 Gate 6: XAI contract holds for the new default model (v3) and fails closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cr005"))
from cr005_helpers import analyses, stream  # noqa: E402

from doctorcar.analysis.explanation import explain  # noqa: E402
from doctorcar.analysis.model import MODEL_V1, MODEL_V3, AnomalyModel  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402


@pytest.fixture(scope="module")
def model():
    return AnomalyModel(MODEL_V3)


@pytest.fixture(scope="module")
def windows(model):
    faulty = stream((ScenarioInstance("S01", 45000, 45000, 1.0),), seed=4100)
    normal = stream(seed=4100)
    return analyses(model, faulty), analyses(model, normal)


def pick(results, decision):
    return next(r for r in results if r.get("decision") == decision)


def test_healthy_trip_raises_no_alarm_so_no_explanation_is_requested(model):
    from doctorcar.analysis.analyzer import AnomalyAnalyzer

    analyzer = AnomalyAnalyzer(model)
    alarms = [t for s in stream(seed=4100) for _, t in [analyzer.push(s)] if t is not None]
    assert alarms == []  # window-level ANOMALOUS decisions alone are not alarms (persistence gate)


def test_anomalous_or_highest_scoring_window_is_explained_from_its_own_model(model, windows):
    faulty, _ = windows
    scored = [r for r in faulty if "score" in r]
    window = next(
        (r for r in scored if r["decision"] == "ANOMALOUS"), max(scored, key=lambda r: r["score"])
    )
    xai = explain(model, window)
    assert xai["status"] == "AVAILABLE"
    assert xai["model_sha256"] == model.metadata["sha256"] == window["model_sha256"]
    assert xai["original_score"] == pytest.approx(window["score"], abs=1e-12)
    assert xai["end_ms"] == window["end_ms"]  # explains the window as scored, no later data
    assert {e["group"] for e in xai["effects"]} >= {"temperature", "air_fuel_operation"}
    text = str(xai).lower()
    assert "root cause" not in text and "damaged" not in text


def test_explanation_is_refused_for_another_model_or_tampered_input(model, windows):
    faulty, _ = windows
    window = max((r for r in faulty if "score" in r), key=lambda r: r["score"])
    with pytest.raises(ValueError):
        explain(AnomalyModel(MODEL_V1), window)  # different model: refused, never mixed
    with pytest.raises(ValueError):
        explain(model, {**window, "score": window["score"] + 0.1})  # stored score != features
    with pytest.raises(ValueError):
        explain(model, {k: v for k, v in window.items() if k != "score"})  # INVALID input
    with pytest.raises(ValueError):
        explain(model, {**window, "feature_names": window["feature_names"][:-1]})


def test_groups_the_model_never_reads_are_flagged_not_reported_as_evidence(model, windows):
    faulty, _ = windows
    window = max((r for r in faulty if "score" in r), key=lambda r: r["score"])
    used = set(model.metadata["selected_feature_indices"])
    for effect in explain(model, window)["effects"]:
        assert effect["used_by_model"] == any(i in used for i in effect["feature_indices"])
