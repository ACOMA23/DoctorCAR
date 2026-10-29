from doctorcar.core.session import Session
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.simulator import device_messages
from doctorcar.sources.serial_device import ProtocolFileSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def test_device_simulator_parser_shared_pipeline(tmp_path):
    path = tmp_path / "device.jsonl"
    path.write_bytes(b"".join(encode_message(m) for m in device_messages("thermal", step_ms=1000)))
    with SQLiteRepository(tmp_path / "device.db") as repo:
        source = ProtocolFileSource(path)
        session = Session(source, repo)
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        assert session.accepted == 156
        assert len(repo.list_events()) == 1
        event = repo.get_event(repo.list_events()[0]["event_id"])
        assert event.status == "COMPLETE"
        assert event.samples[0].device_id == "doctorcar-software-simulator"
        assert event.samples[0].source.value == "SIMULATION"


def test_uploaded_event_passes_same_quality_validator(tmp_path):
    from dataclasses import replace

    from doctorcar.core.models import Event, Quality, Reading, Sample, Trigger
    from doctorcar.protocol.simulator import event_messages

    initial = list(device_messages(step_ms=1000))[:3]
    sample = Sample.from_dict(initial[2]["payload"]["sample"])
    sample = replace(sample, readings={"COOLANT_TEMP": Reading(-999, "°C")})
    event = Event(
        "uploaded-quality",
        sample.session_id,
        Trigger("DATA_QUALITY", "اختبار", "بيانات مرفوعة", "test-v1", 0),
        [sample],
        "COMPLETE",
        0,
    )
    device = initial[0]["device_id"]
    wire = [initial[0], initial[1]] + event_messages(event, device_id=device)
    path = tmp_path / "event.jsonl"
    path.write_bytes(b"".join(encode_message(m) for m in wire))
    with SQLiteRepository(tmp_path / "uploaded.db") as repo:
        session = Session(ProtocolFileSource(path), repo)
        session.start()
        while not session.source.exhausted:
            session.step()
        session.stop()
        saved = repo.get_event(event.event_id)
        assert saved.samples[0].readings["COOLANT_TEMP"].quality == Quality.INVALID
        assert saved.samples[0].raw["readings"]["COOLANT_TEMP"]["value"] == -999
