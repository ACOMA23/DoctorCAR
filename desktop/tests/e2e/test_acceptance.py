"""The eight acceptance scenarios in the user's M1 directive."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from doctorcar.core.session import Session
from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.messages import envelope
from doctorcar.protocol.simulator import event_messages
from doctorcar.sources.serial_device import ProtocolFileSource
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow


def drive(repo, scenario):
    session = Session(SimulationSource(scenario, step_ms=500), repo)
    session.start()
    while not session.source.exhausted:
        session.step()
    session.stop()
    return session


def test_e2e_01_normal_trip_has_no_thermal_event(tmp_path):
    with SQLiteRepository(tmp_path / "normal.db") as repo:
        drive(repo, "normal")
        assert repo.list_events() == []


def test_e2e_02_thermal_event_has_time_based_pre_and_post(tmp_path):
    with SQLiteRepository(tmp_path / "thermal.db") as repo:
        drive(repo, "thermal")
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert event.status == "COMPLETE"
        assert event.samples[0].timestamp_ms == event.trigger.timestamp_ms - 30000
        assert event.samples[-1].timestamp_ms == event.trigger.timestamp_ms + 30000
        assert len(event.samples) == 121
        assert event.trigger.rule_version and event.samples[0].raw


def test_e2e_03_detection_without_dtc(tmp_path):
    with SQLiteRepository(tmp_path / "no-dtc.db") as repo:
        drive(repo, "thermal")
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert all(not s.dtcs for s in event.samples)
        assert event.trigger.kind == "THERMAL_DEMO"


def test_e2e_04_invalid_reading_is_not_sensor_failure(tmp_path):
    with SQLiteRepository(tmp_path / "invalid.db") as repo:
        drive(repo, "invalid")
        event = repo.get_event(repo.list_events()[0]["event_id"])
        report = build_diagnostic_report(event)
        assert event.trigger.kind == "DATA_QUALITY"
        assert "لا يثبت تلف حساس" in report
        assert "الأدلة غير كافية" in report


def test_e2e_05_disconnect_is_not_vehicle_electrical_fault(tmp_path):
    with SQLiteRepository(tmp_path / "disconnect.db") as repo:
        session = Session(SimulationSource(), repo)
        session.start()
        session.step()
        session.record_connection_loss("انقطاع نقل اختباري")
        session.stop()
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert "لا تستنتج عطل كهرباء المركبة" in build_diagnostic_report(event)


def test_e2e_06_restart_retrieves_identical_report(tmp_path):
    path = tmp_path / "restart.db"
    with SQLiteRepository(path) as repo:
        drive(repo, "thermal")
        event_id = repo.list_events()[0]["event_id"]
        report = build_diagnostic_report(repo.get_event(event_id))
    with SQLiteRepository(path) as repo:
        assert build_diagnostic_report(repo.get_event(event_id)) == report


def test_e2e_07_same_event_wire_import_is_idempotent(tmp_path):
    with SQLiteRepository(tmp_path / "origin.db") as origin:
        drive(origin, "thermal")
        event = origin.get_event(origin.list_events()[0]["event_id"])
    messages = [
        envelope(
            "HELLO",
            "dev",
            event.session_id,
            0,
            0,
            "SIMULATION",
            {"firmware_version": "test", "test_mode": True},
        ),
        envelope(
            "CAPABILITIES",
            "dev",
            event.session_id,
            1,
            0,
            "SIMULATION",
            {"sensors": [], "can": False, "microsd": False, "event_upload": True},
        ),
    ]
    upload = event_messages(event, device_id="dev")
    messages.extend(upload)
    messages.extend(event_messages(event, start_sequence=len(upload) + 2, device_id="dev"))
    path = tmp_path / "upload.jsonl"
    path.write_bytes(b"".join(encode_message(m) for m in messages))
    with SQLiteRepository(tmp_path / "destination.db") as repo:
        session = Session(ProtocolFileSource(path), repo)
        session.start()
        while not session.source.exhausted:
            session.step()
        session.stop()
        assert len(repo.list_events()) == 1
        assert repo.get_event(event.event_id).to_dict() == event.to_dict()


def test_e2e_08_ui_pages_keep_one_source_and_restore_report(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "gui.db"

    def wait(condition, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        raise AssertionError("GUI acceptance timed out")

    window = MainWindow(path)
    window.show()
    try:
        wait(lambda: window.backend_ready)
        window.scenario_combo.setCurrentIndex(1)
        window.speed_combo.setCurrentIndex(2)
        window.start_button.click()
        wait(lambda: window.latest is not None)
        for index in range(36):
            window.navigation.setCurrentRow(index % 6)
            app.processEvents()
        wait(lambda: window.latest.timestamp_ms >= 130000)
        wait(lambda: window.events_table.rowCount() == 1)
        assert window.worker.starts == 1
        window.open_event(0, 0)
        wait(lambda: "حدود النتيجة" in window.report_text.toPlainText())
        report = window.report_text.toPlainText()
        assert "المصدر: SIMULATION" in report
    finally:
        window.close()
        wait(lambda: not window.worker.isRunning())
        app.processEvents()
    reopened = MainWindow(path)
    reopened.show()
    try:
        wait(lambda: reopened.events_table.rowCount() == 1)
        reopened.open_event(0, 0)
        wait(lambda: reopened.report_text.toPlainText() == report)
        assert reopened.worker.starts == 0
    finally:
        reopened.close()
        wait(lambda: not reopened.worker.isRunning())
        app.processEvents()
