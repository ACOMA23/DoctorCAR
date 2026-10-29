"""DC-FIX-001 Gate 7: DEF-009 raw errors, DEF-010 empty replay path, DEF-011 DTC language."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from doctorcar.core.models import Quality, Reading, Sample, Source  # noqa: E402
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY  # noqa: E402
from doctorcar.ui.localization import translate  # noqa: E402
from doctorcar.ui.main_window import MainWindow  # noqa: E402
from doctorcar.ui.worker import friendly_error  # noqa: E402

WIN_PATH = "C:" + chr(92) + "Users" + chr(92) + "x" + chr(92) + "secret" + chr(92) + "trip.jsonl"
RAW = (
    "Traceback",
    "Errno",
    "does not appear",
    "No such file",
    "Permission denied",
    "Experimental TCP",
    "C:" + chr(92),
)


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("'999.999.1.1' does not appear to be an IPv4 or IPv6 address"),
        FileNotFoundError(2, "No such file or directory", WIN_PATH),
        PermissionError(13, "Permission denied", "."),
        ValueError("Experimental TCP supports IPv4 loopback only; LAN is disabled"),
        ConnectionRefusedError(10061, "refused"),
        TimeoutError("timed out"),
        ValueError("Replay file must contain a single session"),
        RuntimeError("boom"),
    ],
)
@pytest.mark.parametrize("language", ["ar", "en"])
def test_error_text_is_localized_and_hides_internals(exc, language):
    shown = translate(f"تعذر إكمال العملية: {friendly_error(exc)}", language)
    assert not any(token in shown for token in RAW), shown
    if language == "en":
        assert not any("؀" <= ch <= "ۿ" for ch in shown), shown  # fully translated


def test_missing_file_message_names_the_file_not_the_path():
    assert friendly_error(FileNotFoundError(2, "x", WIN_PATH)) == "الملف غير موجود: trip.jsonl"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app, tmp_path):
    w = MainWindow(tmp_path / "ui.sqlite3")
    w.show()
    yield w
    w.close()
    w.worker.wait(5000)


def sample():
    readings = {k: Reading(10.0, REGISTRY.get(k).unit) for k in NUMERIC_IDS}
    return Sample("trip", Source.SIMULATION, 0, 0, readings, dtc_quality=Quality.AVAILABLE)


def test_start_replay_without_a_path_asks_for_a_file(window):
    window.source_combo.setCurrentIndex(window.source_combo.findData("replay"))
    window.path_input.setText("")
    window.start_source()
    text = window.error_label.text()
    assert "اختر ملف" in text and "Permission" not in text and "'.'" not in text
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert "Select a replay file first" in window.error_label.text()


def test_dtc_cell_follows_the_language_without_waiting_for_a_new_sample(window):
    window.show_sample(sample())
    row = next(i for i, s in enumerate(REGISTRY.all()) if s.kind == "diagnostic")
    assert "لا رمز مرصود" in window.sensor_table.item(row, 2).text()
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert "No code observed" in window.sensor_table.item(row, 2).text()
    window.language_combo.setCurrentIndex(window.language_combo.findData("ar"))
    assert "لا رمز مرصود" in window.sensor_table.item(row, 2).text()


def test_technical_report_lists_a_repeated_check_once():
    import tempfile
    from pathlib import Path

    from doctorcar.core.session import Session
    from doctorcar.diagnostics.human_report import (
        build_report_model,
        load_ai_context,
        render_technical,
    )
    from doctorcar.sources.scenarios import ScenarioInstance
    from doctorcar.sources.simulation import SimulationSource
    from doctorcar.storage.sqlite_repository import SQLiteRepository

    src = SimulationSource(
        seed=4100,
        scenario_family="multisensor",
        mode="FAULT_INJECTION",
        scenarios=(ScenarioInstance("S01", 60000, 35000, 1.0),),
    )
    with SQLiteRepository(Path(tempfile.mkdtemp()) / "r.sqlite3") as repo:
        session = Session(src, repo)
        session.start()
        while not src.exhausted:
            session.step()
        session.stop()
        row = next(r for r in repo.list_events() if r["kind"] == "MS_THERMAL")
        event = repo.get_event(row["event_id"])
        analysis, status, later = load_ai_context(repo, event)
        model = build_report_model(
            event, analysis, repo.get_detections(event.event_id), status, later
        )
        assert len(model.hypotheses) >= 2
        text = render_technical(model, "en").split("Stored AI/XAI")[0]
        check = model.hypotheses[0]["recommended_check_en"]
        assert text.count(check) == 1
        assert "Same check as listed under hypothesis 1." in text
