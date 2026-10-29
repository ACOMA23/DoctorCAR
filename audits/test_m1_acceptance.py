"""Independent M1 acceptance probes. Product code is intentionally left unchanged."""

import json
import os
import sqlite3
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from doctorcar.core.models import Event, Quality, Reading, Sample, Trigger
from doctorcar.core.session import Session
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.receiver import ProtocolReceiver
from doctorcar.protocol.simulator import device_messages, event_messages
from doctorcar.sources.replay import ReplaySource
from doctorcar.sources.serial_device import ProtocolFileSource
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.worker import BackendWorker
from PySide6.QtWidgets import QApplication


def fresh_sample():
    source = SimulationSource()
    source.connect()
    source.start()
    try:
        return source.read_measurements()
    finally:
        source.stop()
        source.disconnect()


def test_fr002_replay_must_not_advertise_explicitly_unsupported_sensor(tmp_path):
    sample = fresh_sample()
    readings = dict(sample.readings)
    readings["MAF"] = Reading(None, "g/s", Quality.UNSUPPORTED)
    sample = replace(sample, readings=readings)
    path = tmp_path / "unsupported.jsonl"
    path.write_text(json.dumps(sample.to_dict()) + "\n", encoding="utf-8")
    source = ReplaySource(path)
    source.connect()
    source.start()
    try:
        replayed = source.read_measurements()
        assert replayed.readings["MAF"].quality == Quality.UNSUPPORTED
        assert "MAF" not in source.get_capabilities().sensors
    finally:
        source.stop()
        source.disconnect()


def test_fr004_data001_replay_rejects_boolean_contract_version(tmp_path):
    data = fresh_sample().to_dict()
    data["sample_version"] = True  # JSON boolean is not integer version 1.
    path = tmp_path / "invalid-version.jsonl"
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    source = ReplaySource(path)
    source.connect()
    source.start()
    try:
        with pytest.raises(ValueError):
            source.read_measurements()
    finally:
        source.stop()
        source.disconnect()


def test_data001_finalized_event_rejects_end_before_trigger_and_last_sample():
    sample = replace(fresh_sample(), timestamp_ms=1000)
    data = {
        "event_version": 1,
        "event_id": "invalid-timing",
        "session_id": sample.session_id,
        "trigger": {
            "kind": "DATA_QUALITY",
            "observation": "audit",
            "reason": "audit",
            "rule_version": "audit-v1",
            "timestamp_ms": 1000,
            "evidence": [],
        },
        "samples": [sample.to_dict()],
        "status": "COMPLETE",
        "end_ms": 0,
        "limitations": [],
    }
    with pytest.raises(ValueError):
        Event.from_dict(data)


def test_fr012_boot_transition_preserves_already_accepted_pending_samples():
    first = list(device_messages(step_ms=1000))[:3]
    second = list(device_messages(step_ms=1000))[:3]
    assert first[0]["session_id"] != second[0]["session_id"]
    receiver = ProtocolReceiver()
    receiver.feed(b"".join(encode_message(m) for m in first + second))
    assert not receiver.errors
    assert [s.session_id for s in receiver.samples] == [
        first[0]["session_id"],
        second[0]["session_id"],
    ]


def test_fr012_live_samples_then_matching_event_upload_are_importable(tmp_path):
    initial = list(device_messages(step_ms=1000))[:3]
    sample = Sample.from_dict(initial[2]["payload"]["sample"])
    event = Event(
        "same-sample-upload",
        sample.session_id,
        Trigger("DATA_QUALITY", "audit", "audit", "audit-v1", sample.timestamp_ms),
        [sample],
        "COMPLETE",
        sample.timestamp_ms,
    )
    wire = initial + event_messages(
        event, start_sequence=3, device_id=initial[0]["device_id"]
    )
    path = tmp_path / "samples-and-upload.jsonl"
    path.write_bytes(b"".join(encode_message(m) for m in wire))
    with SQLiteRepository(tmp_path / "import.db") as repo:
        session = Session(ProtocolFileSource(path), repo)
        session.start()
        try:
            while not session.source.exhausted:
                session.step()
            assert len(repo.list_events()) == 1
        finally:
            session.stop()


def test_fr006_nfr001_export_file_error_is_not_a_connection_loss(tmp_path):
    app = QApplication.instance() or QApplication([])
    worker = BackendWorker(tmp_path / "export.db")
    ready, samples, errors = [], [], []
    worker.initialized.connect(lambda: ready.append(True))
    worker.snapshot.connect(samples.append)
    worker.error.connect(errors.append)

    def wait_until(condition):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        raise AssertionError("Audit worker condition timed out")

    worker.start()
    try:
        wait_until(lambda: bool(ready))
        worker.submit("start", source="simulation", scenario="normal", speed=1)
        wait_until(lambda: bool(samples))
        worker.submit(
            "export",
            session_id=samples[-1].session_id,
            path=str(tmp_path / "missing-parent" / "export.jsonl"),
        )
        wait_until(lambda: bool(errors))
    finally:
        worker.shutdown()
        assert worker.wait(5000), "Audit cleanup could not stop worker"
        app.processEvents()
    with sqlite3.connect(tmp_path / "export.db") as connection:
        kinds = [row[0] for row in connection.execute("SELECT kind FROM events")]
    assert "CONNECTION" not in kinds, (
        "A local export FileNotFoundError generated a connection-loss event despite a healthy source"
    )
