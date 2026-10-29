from typing import Any


def envelope(
    kind: str,
    device_id: str,
    session_id: str,
    sequence_number: int,
    timestamp_ms: int,
    source: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "protocol_version": 1,
        "type": kind,
        "device_id": device_id,
        "session_id": session_id,
        "sequence_number": sequence_number,
        "timestamp_ms": timestamp_ms,
        "source": source,
        "payload": payload,
    }
    if event_id is not None:
        result["event_id"] = event_id
    return result
