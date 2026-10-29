"""Gate 4: causal, session-safe linking of ML analyses to events, with explicit reasons."""

import pytest
from cr005_helpers import FakeRepo, StubAnalyzer, fixture_event, make_source, stream

from doctorcar.analysis import status as ai
from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.model import AnomalyModel
from doctorcar.core.session import Session
from doctorcar.diagnostics.human_report import build_report_model, load_ai_context, render_simple
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def run(tmp_path, scenarios, analyzer, seed=4100, ai_failure=None, source=None, name="linking"):
    source = source or make_source(scenarios, seed)
    with SQLiteRepository(tmp_path / f"{name}.db") as repo:
        session = Session(source, repo, analyzer=analyzer, ai_failure=ai_failure)
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        rows = []
        for row in repo.list_events():
            event = repo.get_event(row["event_id"])
            analysis, status, later = load_ai_context(repo, event)
            rows.append((event, analysis, status, later, repo.get_detections(event.event_id)))
        statuses = repo.connection.execute("select count(*) from event_ai_status").fetchone()[0]
        return rows, statuses


def test_rule_event_at_68_2_links_the_window_that_ended_at_68_0(tmp_path):
    rows, _ = run(tmp_path, (ScenarioInstance("S01", 60000, 35000),), AnomalyAnalyzer())
    event, analysis, status, _later, detections = next(
        r for r in rows if r[0].trigger.kind == "MS_THERMAL"
    )
    assert event.trigger.timestamp_ms == 68200
    assert status["state"] in (ai.ANALYZED_NORMAL, ai.ANALYZED_ANOMALOUS)
    assert status["window_end_ms"] == 68000 and status["age_ms"] == 200
    assert status["detection_ms"] == 68200
    assert analysis["end_ms"] == 68000 and analysis["start_ms"] == 63000
    report = build_report_model(event, analysis, detections, status)
    text = render_simple(report)
    assert ai.message(status["state"], "ar") in text
    assert "لم يُحلل" not in text
    # A normal analysis alone never turns a rule event into an AI detection.
    if status["state"] == ai.ANALYZED_NORMAL:
        assert report.detection_summary["ml"] is False
        assert "اكتشفته القواعد؛ وحلل الذكاء الاصطناعي" in text


def test_no_future_analysis_other_model_or_duplicate_event(tmp_path):
    rows, statuses = run(tmp_path, (ScenarioInstance("S02", 60000, 35000),), AnomalyAnalyzer())
    ids = [e.event_id for e, *_ in rows]
    assert len(ids) == len(set(ids)) and statuses == len(ids)
    for event, analysis, status, later, _ in rows:
        detection = event.trigger.timestamp_ms
        if status["state"] in (ai.ANALYZED_NORMAL, ai.ANALYZED_ANOMALOUS):
            assert analysis["end_ms"] <= detection
            assert 0 <= status["age_ms"] <= status["max_age_ms"]
            assert analysis["session_id"] == event.session_id
            assert analysis["model_sha256"] == status["model_sha256"]
        if later is not None:
            assert later["end_ms"] > detection and later["decision"] == "ANOMALOUS"
            assert later is not analysis


def test_latest_before_is_causal_session_bound_and_age_limited():
    analyzer = AnomalyAnalyzer()
    samples = [
        s for s in stream((ScenarioInstance("S01", 60000, 35000),)) if s.timestamp_ms <= 68200
    ]
    for s in samples:
        analyzer.push(s)
    sid = samples[0].session_id
    assert analyzer.latest_before(sid, 68200)["end_ms"] == 68000
    assert analyzer.latest_before(sid, 67999)["end_ms"] == 67000
    assert analyzer.latest_before(sid, 4000) is None  # first window ends at 5 s
    assert analyzer.latest_before(sid, 70000)["end_ms"] == 68000  # exactly two strides old
    assert analyzer.latest_before(sid, 70001) is None  # older than two strides is refused
    assert analyzer.latest_before("another-session", 68200) is None
    assert analyzer.max_age_ms == 2000


@pytest.mark.parametrize(
    ("result", "state"),
    [
        (
            {"decision": "INSUFFICIENT_DATA", "reason": "sensor_coverage", "end_ms": 67000},
            ai.INSUFFICIENT_DATA,
        ),
        (None, ai.NO_RECENT_ANALYSIS),
    ],
)
def test_reason_is_recorded_when_no_valid_analysis_exists(result, state):
    repo = FakeRepo()
    session = Session(object(), repo, analyzer=StubAnalyzer(result))  # type: ignore[arg-type]
    event = fixture_event()
    session._record_ai_status(event)
    status = repo.statuses[event.event_id]
    assert status["state"] == state and status["reason"]
    assert repo.links == []  # nothing is linked when there is nothing valid to link


def test_disabled_not_loaded_and_failed_states(tmp_path):
    for failure, expected in (
        (None, ai.DISABLED),
        ("ImportError: no sklearn", ai.MODEL_NOT_LOADED),
    ):
        rows, _ = run(
            tmp_path,
            (),
            None,
            ai_failure=failure,
            source=SimulationSource("thermal"),
            name=expected,
        )
        assert rows and {r[2]["state"] for r in rows} == {expected}
        if failure:
            assert all(failure in r[2]["reason"] for r in rows)

    class Broken:
        model = AnomalyModel()
        max_age_ms = 2000

        def push(self, sample):
            raise RuntimeError("intentional inference failure")

    rows, _ = run(tmp_path, (), Broken(), source=SimulationSource("thermal"), name="broken")
    assert {r[2]["state"] for r in rows} == {ai.INFERENCE_FAILED}
    assert all("intentional" in r[2]["reason"] for r in rows)
    text = render_simple(build_report_model(rows[0][0], None, rows[0][4], rows[0][2]))
    assert ai.message(ai.INFERENCE_FAILED, "ar") in text and "intentional" in text


def test_legacy_event_without_status_keeps_original_behaviour(tmp_path):
    rows, _ = run(tmp_path, (), None, source=SimulationSource("thermal"))
    event, analysis, status, later, detections = rows[0]
    legacy = build_report_model(event, None, detections)  # no status record at all
    assert legacy.report_version == "human-report-1"
    assert "لم يُحلل" in render_simple(legacy)
    assert later is None and analysis is None and status["state"] == ai.DISABLED
