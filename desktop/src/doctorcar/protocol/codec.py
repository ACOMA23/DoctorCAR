from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

MAX_LINE_BYTES = 4096  # includes LF
PROTOCOL_VERSION = 1
SCHEMA = json.loads(
    files("doctorcar.protocol").joinpath("device_protocol_v1.schema.json").read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA)


def validate_protocol_version(version: Any) -> None:
    if type(version) is not int or version != PROTOCOL_VERSION:
        raise ValueError("Unsupported protocol version")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def decode_message(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise ValueError("Invalid JSONL framing/size")
    try:
        message = json.loads(
            line.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant
        )
        if not isinstance(message, dict):
            raise ValueError("Envelope must be an object")
        validate_protocol_version(message.get("protocol_version"))
        VALIDATOR.validate(message)
        return cast(dict[str, Any], message)
    except (KeyError, TypeError, UnicodeError, ValidationError, RecursionError) as exc:
        raise ValueError(f"Invalid protocol message: {type(exc).__name__}") from exc


def encode_message(message: dict[str, Any]) -> bytes:
    line = (
        json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    decode_message(line)
    return line
