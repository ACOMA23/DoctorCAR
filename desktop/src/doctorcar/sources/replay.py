"""Bounded JSONL replay with original provenance and an isolated playback session."""

import json
from dataclasses import replace
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from doctorcar.core.interfaces import Capabilities, DataSource
from doctorcar.core.models import Quality, Sample, Source
from doctorcar.monitoring.data_quality import DataQualityValidator


class ReplaySource(DataSource):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: TextIO | None = None
        self.session_id = ""
        self._original_session: str | None = None
        self.sensors: frozenset[str] = frozenset()

    def verify(self) -> dict[str, object]:
        validator = DataQualityValidator()
        identity = None
        sensors: set[str] = set()
        count = 0
        with self.path.open(encoding="utf-8") as stream:
            while line := stream.readline(65_537):
                if len(line.encode("utf-8")) > 65_536:
                    raise ValueError("Replay sample exceeds 64 KiB")
                sample = Sample.from_dict(json.loads(line))
                identity = identity or sample.session_id
                if sample.session_id != identity:
                    raise ValueError("Replay file must contain a single session")
                result = validator.validate_measurement(sample)
                if not result.accepted or any(x.startswith("unit:") for x in result.issues):
                    raise ValueError("Invalid replay sample ordering or units")
                sensors.update(
                    k for k, r in sample.readings.items() if r.quality != Quality.UNSUPPORTED
                )
                if sample.dtc_quality != Quality.UNSUPPORTED:
                    sensors.add("DTC")
                count += 1
        if not count:
            raise ValueError("Empty replay file")
        self.sensors = frozenset(sensors)
        return {"ok": True, "stages": ["FILE_VALID", "SAMPLE_VALID"], "samples": count}

    def connect(self) -> None:
        if self._file is not None:
            raise RuntimeError("Replay is already open")
        self._file = self.path.open(encoding="utf-8")
        self.session_id = str(uuid4())
        self._original_session, self.exhausted = None, False
        self.state = "CONNECTED"

    def read_measurements(self) -> Sample | None:
        if self.state != "RUNNING" or self._file is None:
            return None
        line = self._file.readline(65_537)
        if not line:
            self.exhausted = True
            return None
        if len(line.encode("utf-8")) > 65_536:
            raise ValueError("Replay sample exceeds 64 KiB")
        sample = Sample.from_dict(json.loads(line))
        self.sensors = frozenset(
            k for k, r in sample.readings.items() if r.quality != Quality.UNSUPPORTED
        )
        if sample.dtc_quality != Quality.UNSUPPORTED:
            self.sensors |= frozenset(("DTC",))
        if self._original_session is None:
            self._original_session = sample.session_id
        if self._original_session != sample.session_id:
            raise ValueError("Replay file must contain a single session")
        return replace(
            sample,
            session_id=self.session_id,
            source=Source.REPLAY,
            provenance=sample.provenance or sample.source.value,
            raw=sample.raw or sample.to_dict(),
        )

    def get_capabilities(self) -> Capabilities:
        return Capabilities(self.sensors, "REPLAY")

    def disconnect(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        super().disconnect()
