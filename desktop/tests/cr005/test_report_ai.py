"""Gates 5-6: truthful AI sections, non-misleading XAI and layered user/technical reports."""

import re

import numpy as np
import pytest
from cr005_helpers import analyses, explained, first_with, fixture_event, stream

from doctorcar.analysis import status as ai
from doctorcar.analysis.explanation import GROUP_NAMES, GROUPS, METHOD, explain, group_members
from doctorcar.analysis.model import MODEL_V1, MODEL_V2, AnomalyModel
from doctorcar.analysis.windows import FEATURE_NAMES
from doctorcar.diagnostics.human_report import (
    build_report_model,
    render_simple,
    render_technical,
)
from doctorcar.sources.scenarios import ScenarioInstance

S02 = (ScenarioInstance("S02", 60000, 35000),)


@pytest.fixture(scope="module")
def model():
    return AnomalyModel(MODEL_V1)


@pytest.fixture(scope="module")
def anomalous(model):
    return explained(model, first_with(model, "ANOMALOUS", stream(S02)))


@pytest.fixture(scope="module")
def normal(model):
    return first_with(model, "NORMAL", stream(S02))


def status_for(analysis, state):
    return {
        "state": state,
        "detection_ms": 67600,
        "window_end_ms": analysis["end_ms"],
        "age_ms": 67600 - analysis["end_ms"],
        "model_version": analysis["model_version"],
        "model_sha256": analysis["model_sha256"],
        "score": analysis["score"],
        "threshold": analysis["threshold"],
        "window_start_ms": analysis["start_ms"],
    }


def report(analysis, state, **kwargs):
    event = fixture_event()
    status = status_for(analysis, state) if analysis else {"state": state, "reason": "test reason"}
    return build_report_model(event, analysis, [], status, **kwargs)


def test_normal_analysis_is_stated_and_never_shows_anomaly_factors(normal):
    r = report({**normal, "end_ms": 67400, "start_ms": 62400}, ai.ANALYZED_NORMAL)
    for language in ("ar", "en"):
        text = render_simple(r, language)
        assert ai.message(ai.ANALYZED_NORMAL, language) in text
        assert "العوامل" not in text and "Factors that" not in text
        assert "model effects" not in text
    assert "لا توجد عوامل شذوذ" in render_simple(r, "ar")


def test_anomalous_analysis_explains_only_with_computed_effects(model, anomalous):
    r = report({**anomalous, "end_ms": anomalous["end_ms"]}, ai.ANALYZED_ANOMALOUS)
    text = render_simple(r, "ar")
    assert ai.message(ai.ANALYZED_ANOMALOUS, "ar") in text
    assert "العوامل الأكثر تأثيرًا" in text and "ليست أسبابًا ميكانيكية" in text
    line = next(x for x in text.splitlines() if x.startswith("العوامل الأكثر تأثيرًا"))
    positive = {e["group"] for e in anomalous["xai"]["effects"] if e["effect"] > 1e-8}
    shown = {g for g in GROUP_NAMES if GROUP_NAMES[g][0] in line}
    assert shown and shown <= positive
    assert not re.search(r"[A-Z]{3,}_?[A-Z]*\.(mean|std|slope|coverage)", text)  # no feature ids
    english = render_simple(r, "en")
    assert "model effects, not mechanical causes" in english
    assert "Python" not in text and "Model" not in text
    # The explanation text never claims a part or probability.
    assert "%" not in text.split("العوامل")[1].split("ما المشكلة")[0]


@pytest.mark.parametrize(
    "state",
    [
        ai.INSUFFICIENT_DATA,
        ai.MODEL_NOT_LOADED,
        ai.INFERENCE_FAILED,
        ai.DISABLED,
        ai.HISTORICAL,
        ai.NO_RECENT_ANALYSIS,
    ],
)
def test_every_non_analysis_state_has_its_own_message_not_the_generic_one(state):
    r = report(None, state)
    for language in ("ar", "en"):
        text = render_simple(r, language)
        assert ai.message(state, language) in text
        assert "لم يُحلل هذا الحدث" not in text and "has not been analyzed" not in text
    assert (
        ai.MESSAGES[ai.MODEL_NOT_LOADED][0] == "تحليل الذكاء الاصطناعي غير متاح: النموذج لم يُحمّل."
    )
    assert ai.MESSAGES[ai.INFERENCE_FAILED][0] == "تعذر إكمال التحليل بسبب خطأ تقني."
    assert ai.MESSAGES[ai.INSUFFICIENT_DATA][0] == "لم تتوفر بيانات كافية للتحليل."


def test_later_ai_detection_is_reported_separately_from_what_was_known(anomalous, normal):
    at = {**normal, "end_ms": 67400, "start_ms": 62400}
    later = {**anomalous, "end_ms": 70000, "start_ms": 65000}
    r = report(at, ai.ANALYZED_NORMAL, analysis_later=later)
    text = render_simple(r, "ar")
    assert "بعد الكشف الأول اكتشف الذكاء الاصطناعي" in text and "70.0" in text
    assert "لا يصف ما كان معروفًا لحظة الكشف" in text
    # The decision recorded for the moment of detection is untouched.
    assert ai.message(ai.ANALYZED_NORMAL, "ar") in text and r.analysis["end_ms"] == 67400


def test_detection_sources_are_distinguished(anomalous):
    event = fixture_event("ML_ANOMALY", 67600)

    def detection(kind, at):
        return {
            "kind": kind,
            "observation": "t",
            "reason": "t",
            "rule_version": "v",
            "timestamp_ms": at,
            "evidence": [],
        }

    detections = [detection("ML_ANOMALY", 67600), detection("MS_AIR_FUEL", 70600)]
    r = build_report_model(
        event, anomalous, detections, status_for(anomalous, ai.ANALYZED_ANOMALOUS)
    )
    assert r.detection_summary["combined"] is True
    assert "اكتشفه الذكاء الاصطناعي والقواعد معًا" in render_simple(r, "ar")
    assert "3.0 ثانية" in render_simple(r, "ar")
    rules_only = build_report_model(
        fixture_event(),
        None,
        [{"kind": "THERMAL_DEMO", "timestamp_ms": 67600}],
        {"state": ai.DISABLED},
    )
    assert rules_only.detection_summary == {
        **rules_only.detection_summary,
        "ml": False,
        "combined": False,
        "rule_kinds": ["THERMAL_DEMO"],
    }
    assert "اكتشفته القواعد." in render_simple(rules_only, "ar")


def test_technical_report_has_scores_window_xai_and_limits(anomalous):
    r = report(anomalous, ai.ANALYZED_ANOMALOUS)
    text = render_technical(r, "en")
    for expected in (
        "state: ANALYZED_ANOMALOUS",
        f"model_version: {anomalous['model_version']}",
        f"threshold: {anomalous['threshold']}",
        f"window_end_ms: {anomalous['end_ms']}",
        "recording_window_ms: 37600..97600",
        METHOD,
        "[not read by this model]",
        "Not mechanical causation",
        "feature_units",
    ):
        assert expected in text, expected


def test_explanation_flags_unused_groups_direction_and_feature_effects(model, anomalous):
    xai = anomalous["xai"]
    assert xai["method"] == METHOD and xai["decision"] == "ANOMALOUS"
    used = set(model.metadata["selected_feature_indices"])
    by_group = {e["group"]: e for e in xai["effects"]}
    assert by_group["speed"]["used_by_model"] is False and by_group["speed"]["effect"] == 0.0
    assert all(
        by_group[g]["used_by_model"] for g in ("temperature", "air_fuel_operation", "voltage")
    )
    for e in xai["effects"]:
        assert e["direction"] == (
            "raises_score"
            if e["effect"] > 1e-8
            else "lowers_score"
            if e["effect"] < -1e-8
            else "none"
        )
    x = np.array(anomalous["features"])
    reference = np.array(model.metadata["background"])
    for f in xai["feature_effects"]:
        assert f["index"] in used and FEATURE_NAMES[f["index"]] == f["name"]
        changed = x.copy()
        changed[f["index"]] = reference[f["index"]]
        assert abs(f["effect"] - (anomalous["score"] - float(model.scores([changed])[0]))) < 1e-12
        assert f["relation_to_reference"] == (
            "above" if x[f["index"]] > reference[f["index"]] else "below"
        )
    assert sorted(set(range(len(FEATURE_NAMES))) - used) and not any(
        f["index"] not in used for f in xai["feature_effects"]
    )


def test_v2_reads_every_group_and_other_model_results_are_refused(model, anomalous):
    v2 = AnomalyModel(MODEL_V2)
    result = (
        first_with(v2, "ANOMALOUS", stream(S02))
        if any(r["decision"] == "ANOMALOUS" for r in analyses(v2, stream(S02)))
        else analyses(v2, stream(S02))[60]
    )
    xai = explain(v2, result)
    assert all(e["used_by_model"] for e in xai["effects"])
    assert {i for g in GROUPS.values() for i in group_members(g)} == set(range(len(FEATURE_NAMES)))
    with pytest.raises(ValueError):
        explain(v2, anomalous)  # a v1 result must never be reinterpreted by v2
    with pytest.raises(ValueError):
        explain(model, result)
