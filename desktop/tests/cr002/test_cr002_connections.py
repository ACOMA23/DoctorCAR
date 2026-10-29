import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from doctorcar.core.models import Reading
from doctorcar.core.session import Session
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.simulator import device_messages
from doctorcar.sources import serial_device
from doctorcar.sources.replay import ReplaySource
from doctorcar.sources.serial_device import ProtocolFileSource, SerialDeviceSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


class FakePort:
    def __init__(self, data=b"", failure=False):
        self.data, self.failure = data, failure
        self.opens = self.closes = 0

    def open(self):
        self.opens += 1

    def close(self):
        self.closes += 1

    def read(self, size):
        if self.failure:
            raise serial_device.serial.SerialException("unplugged")
        data, self.data = self.data[:size], self.data[size:]
        return data


def verify_port(monkeypatch, port):
    monkeypatch.setattr(SerialDeviceSource, "available_ports", staticmethod(lambda: ["FAKE"]))
    source = SerialDeviceSource("FAKE", lambda **kwargs: port)
    return source, source.verify()


def test_at011_serial_handshake_and_sample_closes_once(monkeypatch):
    wire = b"".join(encode_message(m) for m in list(device_messages())[:3])
    port = FakePort(wire)
    source, result = verify_port(monkeypatch, port)
    assert result["ok"]
    assert result["stages"] == [
        "PORT_AVAILABLE",
        "CONNECTING",
        "HANDSHAKE_PENDING",
        "HELLO",
        "CAPABILITIES",
        "PROTOCOL_COMPATIBLE",
        "CONNECTED",
        "RECEIVING_DATA",
    ]
    assert result["firmware_version"] == "software-0.1.0"
    assert result["capabilities"]["can"] is False
    assert source.port is None and source.state == "DISCONNECTED"
    assert port.opens == port.closes == 1


@pytest.mark.parametrize("kind", ["timeout", "version", "lost", "unit"])
def test_at011_serial_failure_stages_and_cleanup(monkeypatch, kind):
    messages = list(device_messages())[:3]
    if kind == "version":
        messages[0]["protocol_version"] = 999
        data = (json.dumps(messages[0]) + "\n").encode()
    elif kind == "unit":
        messages[2]["payload"]["sample"]["readings"]["RPM"]["unit"] = "bad"
        data = b"".join(encode_message(m) for m in messages)
    else:
        data = b""
    if kind == "timeout":
        clock = iter(range(100))
        monkeypatch.setattr(
            serial_device,
            "time",
            SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda seconds: None),
        )
    port = FakePort(data, failure=kind == "lost")
    source, result = verify_port(monkeypatch, port)
    assert result["ok"] is False
    assert (
        result["state"]
        == {
            "timeout": "TIMEOUT",
            "version": "PROTOCOL_ERROR",
            "lost": "CONNECTION_LOST",
            "unit": "PROTOCOL_ERROR",
        }[kind]
    )
    assert source.port is None and port.opens == port.closes == 1


def test_at011_protocol_file_distinguishes_schema_from_handshake(tmp_path):
    messages = list(device_messages())[:3]
    path = tmp_path / "wire.jsonl"
    path.write_bytes(encode_message(messages[0]))
    result = ProtocolFileSource(path).verify()
    assert result["file_valid"] and not result["handshake_valid"]
    path.write_bytes(b"".join(encode_message(m) for m in messages))
    assert ProtocolFileSource(path).verify()["ok"]
    path.write_bytes(encode_message(messages[-1]))
    assert ProtocolFileSource(path).verify()["stages"][-1] == "PROTOCOL_ERROR"
    path.write_bytes(b"{}\n")
    with pytest.raises(ValueError):
        ProtocolFileSource(path).verify()


def test_replay_file_validation_and_explicit_capabilities(tmp_path):
    messages = list(device_messages())[:3]
    data = messages[2]["payload"]["sample"]
    data["readings"]["MAF"] = {"value": None, "unit": "g/s", "quality": "UNSUPPORTED"}
    path = tmp_path / "trip.jsonl"
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    source = ReplaySource(path)
    assert source.verify()["ok"] and "MAF" not in source.get_capabilities().sensors
    data["sample_version"] = True
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        source.verify()


def test_at009_multiple_boots_same_read_preserve_sessions_and_samples(tmp_path):
    first, second = list(device_messages())[:3], list(device_messages())[:3]
    path = tmp_path / "boots.jsonl"
    path.write_bytes(b"".join(encode_message(m) for m in first + second))
    with SQLiteRepository(tmp_path / "boots.db") as repo:
        session = Session(ProtocolFileSource(path), repo)
        session.start()
        while not session.source.exhausted:
            session.step()
        session.stop()
        assert session.accepted == 2 and session.rejected == 0
        assert repo.connection.execute("SELECT count(*) FROM measurements").fetchone()[0] == 2
        assert len(repo.list_events()) == 0


def test_semantic_dedup_does_not_ignore_measurement_conflicts(tmp_path):
    from doctorcar.core.models import Sample

    sample = Sample.from_dict(list(device_messages())[2]["payload"]["sample"])
    with SQLiteRepository(tmp_path / "conflict.db") as repo:
        repo.save_session(sample.session_id, sample.source.value)
        repo.save_measurement(sample)
        repo.save_measurement(replace(sample, received_at_ms=123, device_id="host-copy"))
        readings = dict(sample.readings)
        readings["RPM"] = Reading(999, "rpm")
        with pytest.raises(ValueError, match="Conflicting"):
            repo.save_measurement(replace(sample, readings=readings))
