"""Repeatable real local run. Writes measured evidence, never touches hardware."""

import json
import time
from pathlib import Path

from doctorcar.core.session import Session
from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.simulator import device_messages
from doctorcar.sources.serial_device import ProtocolFileSource
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    directory = root / "data" / f"verification-{time.time_ns()}"
    directory.mkdir(parents=True)
    evidence = root / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    started = time.monotonic()
    for scenario in ("normal", "thermal", "invalid", "dropout", "device_protocol"):
        database = directory / f"{scenario}.sqlite3"
        if scenario == "device_protocol":
            wire = directory / "device.jsonl"
            wire.write_bytes(
                b"".join(
                    encode_message(m) for m in device_messages("thermal", step_ms=1000)
                )
            )
            source = ProtocolFileSource(wire)
        else:
            source = SimulationSource(scenario, step_ms=1000)
        with SQLiteRepository(database) as repository:
            session = Session(source, repository)
            session.start()
            while not source.exhausted:
                session.step()
            session.stop()
            events = repository.list_events()
            saved = []
            for row in events:
                event = repository.get_event(row["event_id"])
                assert event is not None and event.status == "COMPLETE"
                report = build_diagnostic_report(event)
                (evidence / f"report-{scenario}.txt").write_text(
                    report, encoding="utf-8"
                )
                saved.append(
                    {
                        "event_id": event.event_id,
                        "kind": event.trigger.kind,
                        "trigger_ms": event.trigger.timestamp_ms,
                        "first_ms": event.samples[0].timestamp_ms,
                        "last_ms": event.samples[-1].timestamp_ms,
                        "sample_count": len(event.samples),
                        "status": event.status,
                    }
                )
            assert len(events) == (0 if scenario == "normal" else 1)
            accepted = session.accepted
        with SQLiteRepository(database) as reopened:
            assert reopened.list_events() == events
        results.append(
            {
                "scenario": scenario,
                "accepted": accepted,
                "events": saved,
                "reload_verified": True,
            }
        )
    output = {
        "source": "LOCAL_SIMULATION_ONLY",
        "results": results,
        "wall_duration_seconds": round(time.monotonic() - started, 3),
        "database_directory": str(directory),
        "physical_device_tested": False,
    }
    (evidence / "e2e-run.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
