import copy
import json
from dataclasses import replace

import pytest

from doctorcar.core.models import Event, Quality, Trigger
from doctorcar.protocol.codec import MAX_LINE_BYTES, decode_message, encode_message
from doctorcar.protocol.messages import envelope
from doctorcar.protocol.receiver import ProtocolReceiver
from doctorcar.protocol.simulator import device_messages, event_messages
from doctorcar.sources.serial_device import SerialDeviceSource


def handshake(receiver, session="test", start=0):
    receiver.feed(
        encode_message(
            envelope(
                "HELLO",
                "dev",
                session,
                start,
                0,
                "SIMULATION",
                {"firmware_version": "test", "test_mode": True},
            )
        )
    )
    receiver.feed(
        encode_message(
            envelope(
                "CAPABILITIES",
                "dev",
                session,
                start + 1,
                0,
                "SIMULATION",
                {"sensors": ["RPM"], "can": False, "microsd": False, "event_upload": True},
            )
        )
    )


def test_roundtrip_every_type_and_fragmented_simulator():
    messages = list(device_messages(step_ms=1000))
    receiver = ProtocolReceiver()
    for m in messages:
        wire = encode_message(m)
        assert decode_message(wire) == m
        for i in range(0, len(wire), 17):
            receiver.feed(wire[i : i + 17])
    assert not receiver.errors and len(receiver.samples) == 156
    assert receiver.sequence_gaps == 0
    assert all(s.source.value == "SIMULATION" for s in receiver.samples)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda m: m.update(protocol_version=2),
        lambda m: m.update(protocol_version=True),
        lambda m: m.update(type="CLEAR_DTC"),
        lambda m: m.update(sequence_number=-1),
        lambda m: m.update(source="REAL"),
        lambda m: m.update(payload={}),
        lambda m: m.update(extra="bad"),
    ],
)
def test_reject_invalid_envelope(mutator):
    message = next(device_messages())
    mutator(message)
    wire = (json.dumps(message) + "\n").encode()
    with pytest.raises(ValueError):
        decode_message(wire)


@pytest.mark.parametrize(
    "wire",
    [
        b"{}",
        b"{bad}\n",
        b"[]\n",
        b"\xff\n",
        b'{"x":NaN}\n',
        b'{"x":1,"x":2}\n',
        b"a" * 4097 + b"\n",
    ],
)
def test_reject_malformed_framing(wire):
    with pytest.raises(ValueError):
        decode_message(wire)


def test_oversize_resynchronization():
    receiver = ProtocolReceiver()
    receiver.feed(b"x" * (MAX_LINE_BYTES + 1))
    receiver.feed(b"rest\n" + encode_message(next(device_messages())))
    assert receiver.identity is not None
    assert "oversized_line" in receiver.errors


def test_handshake_required_duplicate_gap_reconnect_and_source_mismatch():
    messages = list(device_messages(step_ms=1000))[:6]
    receiver = ProtocolReceiver()
    receiver.feed(encode_message(messages[2]))
    assert receiver.errors and not receiver.samples
    receiver.reset_connection()
    for m in messages[:3]:
        receiver.feed(encode_message(m))
    receiver.feed(encode_message(messages[2]))
    assert len(receiver.samples) == 1
    receiver.feed(encode_message(messages[4]))  # drop heartbeat seq=3
    assert receiver.sequence_gaps == 1
    bad = copy.deepcopy(messages[5])
    bad["source"] = "DEVICE_TEST"
    receiver.feed(encode_message(bad))
    assert receiver.errors
    receiver.reset_connection()
    hello = copy.deepcopy(messages[0])
    caps = copy.deepcopy(messages[1])
    hello["sequence_number"], caps["sequence_number"] = 20, 21
    receiver.feed(encode_message(hello) + encode_message(caps))
    s = copy.deepcopy(messages[4])
    s["sequence_number"] = 22
    receiver.feed(encode_message(s))
    assert len(receiver.samples) == 1


def test_partial_sensor_support_is_not_zero():
    message = list(device_messages(step_ms=1000))[2]
    sample = message["payload"]["sample"]
    sample["session_id"] = "test"
    sample["readings"] = {"RPM": sample["readings"]["RPM"]}
    receiver = ProtocolReceiver()
    handshake(receiver)
    message.update(device_id="dev", session_id="test")
    receiver.feed(encode_message(message))
    assert receiver.samples[0].readings["MAF"].quality == Quality.UNSUPPORTED
    assert receiver.samples[0].readings["MAF"].value is None


def make_event():
    from doctorcar.core.models import Sample

    m = list(device_messages(step_ms=1000))[2]
    s = Sample.from_dict(m["payload"]["sample"])
    s = replace(s, session_id="test")
    return Event(
        "event-1", "test", Trigger("TEST", "ملاحظة", "اختبار", "v1", 0), [s], "COMPLETE", 0
    )


def test_chunk_reassembly_integrity_repeat_import(tmp_path):
    from doctorcar.storage.sqlite_repository import SQLiteRepository

    event = make_event()
    receiver = ProtocolReceiver()
    handshake(receiver)
    messages = event_messages(event, device_id="dev")
    for m in messages:
        receiver.feed(encode_message(m))
    assert not receiver.errors and len(receiver.events) == 1
    restored = receiver.events.popleft()
    assert restored.to_dict() == event.to_dict()
    with SQLiteRepository(tmp_path / "import.db") as repo:
        repo.save_event(restored)
        repo.save_event(restored)
        assert len(repo.list_events()) == 1
    for m in event_messages(event, start_sequence=100, device_id="dev"):
        receiver.feed(encode_message(m))
    assert len(receiver.events) == 1


@pytest.mark.parametrize("mode", ["corrupt", "missing", "wrong_end", "disconnect"])
def test_incomplete_or_corrupt_event_not_imported(mode):
    receiver = ProtocolReceiver()
    handshake(receiver)
    messages = event_messages(make_event(), device_id="dev")
    if mode == "corrupt":
        messages[1]["payload"]["sha256"] = "0" * 64
    elif mode == "missing":
        del messages[1]
    elif mode == "wrong_end":
        messages[-1]["payload"]["sha256"] = "0" * 64
    for i, m in enumerate(messages):
        if mode == "disconnect" and i == len(messages) - 1:
            receiver.reset_connection()
        receiver.feed(encode_message(m))
    assert not receiver.events and receiver.errors


def test_serial_fake_transport_cleanup_disconnect_reconnect():
    class FakePort:
        def __init__(self, **kwargs):
            self.data = b"".join(encode_message(m) for m in list(device_messages(step_ms=1000))[:5])
            self.closed = True

        def open(self):
            self.closed = False

        def close(self):
            self.closed = True

        def read(self, size):
            result, self.data = self.data[:size], self.data[size:]
            return result

    source = SerialDeviceSource("FAKE", FakePort)
    source.connect()
    source.start()
    first = source.read_measurements()
    assert first is not None and first.source.value == "SIMULATION"
    port = source.port
    source.stop()
    source.disconnect()
    assert port.closed and source.port is None
    source.connect()
    source.start()
    assert source.read_measurements() is not None  # distinct new software boot/session
    source.disconnect()


@pytest.mark.parametrize(
    "kind,payload",
    [("ACK", {"ack_sequence": 2}), ("ERROR", {"code": "INVALID_MESSAGE", "message": "test error"})],
)
def test_ack_error_roundtrip(kind, payload):
    message = envelope(kind, "dev", "test", 2, 0, "DEVICE_TEST", payload)
    assert decode_message(encode_message(message)) == message


def test_serial_attach_midstream_then_handshake_and_timeout(monkeypatch):
    messages = list(device_messages(step_ms=1000))[:5]

    class Port:
        def __init__(self, **kwargs):
            self.fragments = [
                encode_message(messages[2]),
                encode_message(messages[0]) + encode_message(messages[1]),
                encode_message(messages[4]),
            ]

        def open(self):
            pass

        def close(self):
            pass

        def read(self, size):
            return self.fragments.pop(0) if self.fragments else b""

    clock = [0.0]
    monkeypatch.setattr("doctorcar.sources.serial_device.time.monotonic", lambda: clock[0])
    source = SerialDeviceSource("FAKE", Port)
    source.connect()
    source.start()
    assert source.read_measurements() is None
    assert source.read_measurements() is None
    assert source.read_measurements() is not None
    clock[0] = 11
    with pytest.raises(TimeoutError):
        source.read_measurements()
    source.disconnect()


def test_event_nonincreasing_times_and_session_rejected():
    event = make_event()
    data = event.to_dict()
    data["samples"].append(data["samples"][0])
    with pytest.raises(ValueError):
        Event.from_dict(data)
