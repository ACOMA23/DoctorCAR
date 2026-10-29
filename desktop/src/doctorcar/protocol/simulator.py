"""Software device emits exactly the JSONL v1 wire contract, with SIMULATION source."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from doctorcar.core.models import Event
from doctorcar.core.sensor_registry import NUMERIC_IDS
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.messages import envelope
from doctorcar.sources.simulation import SCENARIOS, SimulationSource


def device_messages(
    scenario: str = "normal", seed: int = 42, step_ms: int = 200
) -> Iterator[dict[str, Any]]:
    source = SimulationSource(scenario, seed, step_ms)
    source.connect()
    source.start()
    device, session, seq = "doctorcar-software-simulator", source.session_id, 0
    yield envelope(
        "HELLO",
        device,
        session,
        seq,
        0,
        "SIMULATION",
        {"firmware_version": "software-0.1.0", "test_mode": True},
    )
    seq += 1
    yield envelope(
        "CAPABILITIES",
        device,
        session,
        seq,
        0,
        "SIMULATION",
        {
            "sensors": list((*NUMERIC_IDS, "DTC")),
            "can": False,
            "microsd": False,
            "event_upload": True,
        },
    )
    seq += 1
    try:
        while (sample := source.read_measurements()) is not None:
            yield envelope(
                "SAMPLE",
                device,
                session,
                seq,
                sample.timestamp_ms,
                "SIMULATION",
                {"sample": sample.to_dict()},
            )
            seq += 1
            if sample.timestamp_ms % 1000 == 0:
                yield envelope(
                    "HEARTBEAT",
                    device,
                    session,
                    seq,
                    sample.timestamp_ms,
                    "SIMULATION",
                    {"uptime_ms": sample.timestamp_ms},
                )
                seq += 1
    finally:
        source.stop()
        source.disconnect()


def event_messages(
    event: Event, start_sequence: int = 2, device_id: str = "doctorcar-software-simulator"
) -> list[dict[str, Any]]:
    data = json.dumps(
        event.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    parts = [data[i : i + 768] for i in range(0, len(data), 768)]
    digest = hashlib.sha256(data).hexdigest()
    base = (device_id, event.session_id)
    source = event.samples[0].source.value
    messages = [
        envelope(
            "EVENT_START",
            *base,
            start_sequence,
            event.trigger.timestamp_ms,
            source,
            {"total_chunks": len(parts), "total_bytes": len(data), "sha256": digest},
            event.event_id,
        )
    ]
    for index, part in enumerate(parts):
        messages.append(
            envelope(
                "EVENT_CHUNK",
                *base,
                start_sequence + index + 1,
                event.trigger.timestamp_ms,
                source,
                {
                    "index": index,
                    "data": base64.b64encode(part).decode("ascii"),
                    "sha256": hashlib.sha256(part).hexdigest(),
                },
                event.event_id,
            )
        )
    messages.append(
        envelope(
            "EVENT_END",
            *base,
            start_sequence + len(parts) + 1,
            event.trigger.timestamp_ms,
            source,
            {"sha256": digest},
            event.event_id,
        )
    )
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description="DoctorCAR software device; never vehicle data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="thermal")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pace", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as stream:
        for message in device_messages(args.scenario, args.seed):
            stream.write(encode_message(message))
            if args.pace and message["type"] == "SAMPLE":
                stream.flush()
                time.sleep(0.2)
    print(f"SIMULATION JSONL written to {args.output}")


if __name__ == "__main__":
    main()
