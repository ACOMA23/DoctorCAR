"""Gate 8: simulation/IoT -> quality -> window -> ML + rules -> T+-30 -> SQLite -> report -> UI."""

import json
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict

import pytest
from cr005_helpers import make_source, stream
from PySide6.QtWidgets import QApplication

from doctorcar.analysis import status as ai
from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.model import DEFAULT_MODEL
from doctorcar.core.models import Quality, Reading
from doctorcar.core.session import Session
from doctorcar.diagnostics.human_report import build_report_model, load_ai_context, render_simple
from doctorcar.sources.network_device import NetworkDeviceSource
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow


def run_session(path, source, analyzer=None):
    with SQLiteRepository(path) as repo:
        session = Session(source, repo, analyzer=analyzer)
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        events = [repo.get_event(r["event_id"]) for r in repo.list_events()]
        statuses = {e.event_id: repo.get_event_ai_status(e.event_id) for e in events}
        return session, events, statuses


def check_recording(events):
    for e in events:
        if e.origin == "LIVE" and e.status == "COMPLETE" and e.trigger.timestamp_ms >= 30000:
            assert e.samples[0].timestamp_ms == e.trigger.timestamp_ms - 30000
            assert e.samples[-1].timestamp_ms == e.trigger.timestamp_ms + 30000
            assert len(e.samples) == 301
    assert len({e.event_id for e in events}) == len(events)


def test_multiple_simultaneous_and_intermittent_faults_keep_recording_and_status(tmp_path):
    scenarios = (
        ScenarioInstance("S01", 40000, 45000),
        ScenarioInstance("S02", 60000, 35000),
        ScenarioInstance("S06", 100000, 20000),
    )
    session, events, statuses = run_session(
        tmp_path / "multi.db", make_source(scenarios), AnomalyAnalyzer()
    )
    assert session.accepted == 776
    check_recording(events)
    assert {e.trigger.kind for e in events} >= {"MS_THERMAL", "MS_AIR_FUEL"}
    assert all(s is not None and s["state"] in ai.STATES for s in statuses.values())
    short = [e for e in events if e.trigger.kind == "MS_COMBUSTION"]
    assert short and all(
        e.samples[-1].timestamp_ms >= e.trigger.timestamp_ms + 29000 for e in short
    )


def test_missing_data_and_unsupported_sensor_never_become_a_normal_ai_result(tmp_path):
    class NoMaf(SimulationSource):
        def read_measurements(self):
            sample = super().read_measurements()
            if sample is not None:
                sample.readings["MAF"] = Reading(None, "g/s", Quality.UNSUPPORTED)
            return sample

    source = NoMaf(seed=4100, scenario_family="multisensor", mode="NORMAL")
    session, events, _ = run_session(tmp_path / "nomaf.db", source, AnomalyAnalyzer())
    assert session.ai_status["decision"] == "INSUFFICIENT_DATA"
    assert not [e for e in events if e.trigger.kind == "ML_ANOMALY"]
    dropout = ScenarioInstance("S07", 60000, 20000, 1.0, "dropout")
    _, events, statuses = run_session(
        tmp_path / "dropout.db", make_source((dropout,)), AnomalyAnalyzer()
    )
    quality = [e for e in events if e.trigger.kind in ("DATA_QUALITY", "MS_SIGNAL")]
    assert quality and all(statuses[e.event_id]["state"] in ai.STATES for e in quality)
    check_recording(events)


def test_every_operating_phase_is_scored_and_normal_driving_raises_no_ml_event():
    analyzer, phases, triggers = AnomalyAnalyzer(), {}, []
    for sample in stream(driving_scale=1.0, warm_start=False):
        result, trigger = analyzer.push(sample)
        if result is not None and result["decision"] != "INSUFFICIENT_DATA":
            phases.setdefault(sample.phase, []).append(result["decision"])
        if trigger:
            triggers.append(trigger.timestamp_ms)
    assert set(phases) >= {"إحماء", "خمول", "تسارع", "سير مستقر", "تباطؤ", "محرك متوقف"}
    assert triggers == []  # window-level noise is absorbed by the persistence policy


def start_device(tmp_path):
    ready = tmp_path / "ready.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "doctorcar.protocol.network_simulator",
            "--port",
            "0",
            "--speed",
            "100",
            "--history",
            str(tmp_path / "history.json"),
            "--ready",
            str(ready),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    return process, json.loads(ready.read_text())["port"]


def test_loopback_device_live_ai_history_reports_and_restart_are_consistent(tmp_path):
    process, port = start_device(tmp_path)
    path = tmp_path / "tcp.db"
    try:
        for attempt in range(2):
            with SQLiteRepository(path) as repo:
                source = NetworkDeviceSource(port=port)
                session = Session(
                    source, repo, analyzer=AnomalyAnalyzer() if attempt == 0 else None
                )
                session.start()
                deadline = time.monotonic() + 30
                try:
                    while session.accepted < 776 and time.monotonic() < deadline:
                        session.step()
                        time.sleep(0.0001)
                    assert session.accepted == 776
                finally:
                    session.stop()
                rows = repo.list_events()
                history = [r for r in rows if r["origin"] == "HISTORICAL"]
                live = [r for r in rows if r["origin"] == "LIVE"]
                assert len(history) == 2 and live
                for r in history:
                    assert repo.get_event_ai_status(r["event_id"])["state"] == ai.HISTORICAL
                    assert repo.get_event_analysis(r["event_id"]) is None
                if attempt == 0:
                    states = {repo.get_event_ai_status(r["event_id"])["state"] for r in live}
                    assert states <= {
                        ai.ANALYZED_NORMAL,
                        ai.ANALYZED_ANOMALOUS,
                        ai.NO_RECENT_ANALYSIS,
                    }
                    reports = repo.connection.execute(
                        "select data_json from diagnostic_reports"
                    ).fetchall()
                    assert reports and all(
                        json.loads(r[0])["report_version"] == "human-report-2" for r in reports
                    )
                    first = {r["event_id"]: repo.get_event_ai_status(r["event_id"]) for r in live}
                else:
                    assert all(repo.get_event_ai_status(i) == first[i] for i in first)
                assert repo.connection.execute("pragma integrity_check").fetchone()[0] == "ok"
    finally:
        process.terminate()
        process.communicate(timeout=5)


def wait(app, predicate, seconds=40):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_ui_runs_ai_shows_status_reports_languages_and_themes_without_freezing(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "ui.db"
    window = MainWindow(path)
    window.show()
    ticks = []
    from PySide6.QtCore import QTimer

    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    try:
        wait(app, lambda: window.backend_ready)
        window.worker.submit(
            "start",
            source="simulation",
            ai_enabled=True,
            seed=4100,
            speed=30.0,
            mode="FAULT_INJECTION",
            scenario_family="multisensor",
            scenarios=[asdict(ScenarioInstance("S01", 60000, 35000))],
        )
        db = sqlite3.connect(path)
        wait(
            app,
            lambda: (
                db.execute("select count(*) from events where status='COMPLETE'").fetchone()[0] >= 1
            ),
            60,
        )
        window.worker.submit("stop")
        wait(app, lambda: "iforest-cr006-v3" in window.ai_label.text())
        wait(app, lambda: window.events_table.rowCount() > 0)
        event_id = db.execute(
            "select event_id from events where kind='MS_THERMAL' and status='COMPLETE'"
        ).fetchone()[0]
        for language, marker in (
            ("ar", "ماذا لاحظ الذكاء الاصطناعي؟"),
            ("en", "What did AI observe?"),
        ):
            window.worker.submit("report", event_id=event_id, language=language)
            wait(app, lambda m=marker: m in window.simple_report_text.toPlainText())
            text = window.simple_report_text.toPlainText()
            assert "لم يُحلل هذا الحدث" not in text
        window.technical_button.setChecked(True)
        wait(app, lambda: "state:" in window.report_text.toPlainText())
        window.language_combo.setCurrentIndex(1)
        window.theme_combo.setCurrentIndex(1)
        app.processEvents()
        assert window.language == "en" and window.theme == "dark"
        tooltip = window.events_table.item(0, 8).toolTip()
        assert any(ai.message(s, "en") in tooltip for s in ai.STATES)
        window.show_ai({"decision": "UNAVAILABLE", "state": "MODEL_NOT_LOADED", "reason": "x"})
        assert "model not loaded" in window.ai_label.text()
        window.language_combo.setCurrentIndex(0)
        window.show_ai({"decision": "UNAVAILABLE", "state": "MODEL_NOT_LOADED", "reason": "x"})
        assert "النموذج لم يُحمّل" in window.ai_label.text()
        assert len(ticks) > 20  # the event loop stayed responsive while the backend ran
        db.close()
    finally:
        timer.stop()
        window.worker.shutdown()
        assert window.worker.wait(5000)
        window.close()
    with SQLiteRepository(path) as repo:
        event = repo.get_event(event_id)
        analysis, status, later = load_ai_context(repo, event)
        assert status["state"] in ai.STATES
        report = build_report_model(event, analysis, repo.get_detections(event_id), status, later)
        assert ai.message(status["state"], "ar") in render_simple(report)


@pytest.mark.parametrize("name", [DEFAULT_MODEL])
def test_default_model_is_the_one_applications_record(name, tmp_path):
    session, _, _ = run_session(tmp_path / "d.db", make_source(), AnomalyAnalyzer())
    assert session.analyzer is not None
    assert session.analyzer.model.name == name
