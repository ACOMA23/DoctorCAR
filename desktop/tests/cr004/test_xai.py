import copy

import numpy as np
import pytest
from test_ml import stream

from doctorcar.analysis.explanation import explain
from doctorcar.analysis.model import AnomalyModel
from doctorcar.analysis.windows import FEATURE_NAMES, extract
from doctorcar.sources.scenarios import ScenarioInstance


def test_explanation_fidelity_model_window_reference_and_noncausal_limits():
    model = AnomalyModel()
    result = model.infer(extract(tuple(stream((ScenarioInstance("S01"),))[350:376])))
    xai = explain(model, result)
    assert xai["end_ms"] == 75000 and xai["start_ms"] == 70000
    assert xai["model_sha256"] == result["model_sha256"]
    assert xai["reference_values"] == model.metadata["background"]
    for effect in xai["effects"]:
        # Independently recompute the stated counterfactual through the real pipeline.
        changed = list(result["features"])
        for i in effect["feature_indices"]:
            changed[i] = xai["reference_values"][i]
        score = float(-model.pipeline.score_samples(np.array([changed]))[0])
        assert abs(effect["replacement_score"] - score) < 1e-12
        assert abs(effect["effect"] - (result["score"] - score)) < 1e-12
    assert "Non-additive" in xai["limitations"]
    assert "Not mechanical causation" in xai["limitations"]
    assert xai["elapsed_ms"] > 0
    assert len(result["features"]) == len(FEATURE_NAMES)


def test_changed_inputs_change_explanation_and_old_model_never_reinterpreted():
    model = AnomalyModel()
    a = model.infer(extract(tuple(stream()[350:376])))
    b = model.infer(extract(tuple(stream((ScenarioInstance("S02"),))[350:376])))
    assert explain(model, a)["effects"] != explain(model, b)["effects"]
    bad = copy.deepcopy(a)
    bad["model_sha256"] = "different-model"
    with pytest.raises(ValueError):
        explain(model, bad)
    with pytest.raises(ValueError):
        explain(model, {"decision": "INSUFFICIENT_DATA"})
