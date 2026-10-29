"""Independent local software device. No cloud, CAN, hardware or outbound commands."""

import argparse
import json
import socket
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from doctorcar.core.models import Event
from doctorcar.core.sensor_registry import NUMERIC_IDS
from doctorcar.protocol.codec import encode_message
from doctorcar.protocol.messages import envelope
from doctorcar.protocol.simulator import event_messages
from doctorcar.sources.device_simulator import historical_events
from doctorcar.sources.network_device import local_host
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource

DEVICE = "doctorcar-loopback-simulator"


def announce(session: str) -> Iterator[dict[str, Any]]:
    yield envelope(
        "HELLO",
        DEVICE,
        session,
        0,
        0,
        "SIMULATION",
        {"firmware_version": "software-tcp-1", "test_mode": True},
    )
    yield envelope(
        "CAPABILITIES",
        DEVICE,
        session,
        1,
        0,
        "SIMULATION",
        {
            "sensors": list(NUMERIC_IDS) + ["DTC"],
            "can": False,
            "microsd": False,
            "event_upload": True,
        },
    )


def serve(
    host: str,
    port: int,
    history_path: Path,
    ready: Path | None,
    speed: float,
    scenario: str,
    disconnect_at_ms: int | None,
    max_connections: int,
) -> None:
    host = local_host(host)
    if not 0 <= port <= 65535 or not 1 <= speed <= 100:
        raise ValueError("Invalid server configuration")
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if not history_path.exists():
        history_path.write_text(
            json.dumps([e.to_dict() for e in historical_events()], ensure_ascii=False),
            encoding="utf8",
        )
    history = [Event.from_dict(e) for e in json.loads(history_path.read_text(encoding="utf8"))]
    with socket.socket() as server:
        server.bind((host, port))
        server.listen(1)
        if ready:
            ready.parent.mkdir(parents=True, exist_ok=True)
            ready.write_text(
                json.dumps({"port": server.getsockname()[1], "history_events": len(history)}),
                encoding="utf8",
            )
        print(f"SIMULATION listening at {server.getsockname()}", flush=True)
        connections = 0
        while not max_connections or connections < max_connections:
            connection, _ = server.accept()
            connections += 1
            with connection:
                connection.settimeout(5)

                def send(message: dict[str, Any], client: socket.socket = connection) -> None:
                    client.sendall(encode_message(message))

                try:
                    # This persisted history predates the application connection; not original AI.
                    for event in history:
                        for message in announce(event.session_id):
                            send(message)
                        for message in event_messages(event, device_id=DEVICE):
                            send(message)
                    source = SimulationSource(
                        seed=904,
                        scenario_family="multisensor",
                        mode="NORMAL" if scenario == "normal" else "FAULT_INJECTION",
                        scenarios=() if scenario == "normal" else (ScenarioInstance(scenario),),
                    )
                    source.connect()
                    source.start()
                    for message in announce(source.session_id):
                        send(message)
                    seq = 2
                    while (sample := source.read_measurements()) is not None:
                        send(
                            envelope(
                                "SAMPLE",
                                DEVICE,
                                source.session_id,
                                seq,
                                sample.timestamp_ms,
                                "SIMULATION",
                                {"sample": sample.to_dict()},
                            )
                        )
                        seq += 1
                        if sample.timestamp_ms % 1000 == 0:
                            send(
                                envelope(
                                    "HEARTBEAT",
                                    DEVICE,
                                    source.session_id,
                                    seq,
                                    sample.timestamp_ms,
                                    "SIMULATION",
                                    {"uptime_ms": sample.timestamp_ms},
                                )
                            )
                            seq += 1
                        if disconnect_at_ms is not None and sample.timestamp_ms >= disconnect_at_ms:
                            break
                        time.sleep(0.2 / speed)
                    source.disconnect()
                    if disconnect_at_ms is None:
                        # Idle heartbeat keeps the live device connection open until explicit stop.
                        while True:
                            send(
                                envelope(
                                    "HEARTBEAT",
                                    DEVICE,
                                    source.session_id,
                                    seq,
                                    155000,
                                    "SIMULATION",
                                    {"uptime_ms": 155000},
                                )
                            )
                            seq += 1
                            time.sleep(1)
                except (ConnectionError, OSError):
                    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local JSONL1 simulated device; no physical vehicle"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--history", type=Path, default=Path("data/tcp-device-history.json"))
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--speed", type=float, default=1)
    parser.add_argument(
        "--scenario", choices=["normal"] + [f"S{i:02}" for i in range(1, 8)], default="S02"
    )
    parser.add_argument("--disconnect-at-ms", type=int)
    parser.add_argument("--max-connections", type=int, default=0)
    args = parser.parse_args()
    serve(
        args.host,
        args.port,
        args.history,
        args.ready,
        args.speed,
        args.scenario,
        args.disconnect_at_ms,
        args.max_connections,
    )


if __name__ == "__main__":
    main()
