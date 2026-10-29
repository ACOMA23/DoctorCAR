"""One repository per owning thread. Checkpoint each accepted event sample."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from doctorcar.core.models import Event, Sample


def serialize(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )


def event_metadata(event: Event) -> dict[str, Any]:
    return {
        "event_version": 1,
        "event_id": event.event_id,
        "session_id": event.session_id,
        "trigger": asdict(event.trigger),
        "status": event.status,
        "end_ms": event.end_ms,
        "limitations": event.limitations,
        "origin": event.origin,
    }


def semantic_sample(data: dict[str, Any]) -> dict[str, Any]:
    """Host receipt metadata can vary; measurements, source and provenance cannot."""
    return {k: v for k, v in data.items() if k not in ("received_at_ms", "raw", "device_id")}


def semantic_event(event: Event) -> dict[str, Any]:
    data = event.to_dict()
    data["samples"] = [semantic_sample(s.to_dict()) for s in event.samples]
    return data


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=2)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            self.connection.close()
            raise ValueError(f"Unsupported database version {version}")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                started_at_ms INTEGER NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS measurements (
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                sequence_number INTEGER NOT NULL, timestamp_ms INTEGER NOT NULL,
                data_json TEXT NOT NULL, PRIMARY KEY(session_id, sequence_number));
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
                trigger_ms INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                metadata_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS event_samples (
                event_id TEXT NOT NULL REFERENCES events(event_id),
                session_id TEXT NOT NULL, sequence_number INTEGER NOT NULL,
                PRIMARY KEY(event_id, session_id, sequence_number),
                FOREIGN KEY(session_id, sequence_number)
                    REFERENCES measurements(session_id, sequence_number));
            CREATE INDEX IF NOT EXISTS measurements_time ON measurements(session_id, timestamp_ms);
            CREATE TABLE IF NOT EXISTS simulation_runs (
                session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
                metadata_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS extension_migrations (
                name TEXT PRIMARY KEY, version INTEGER NOT NULL);
            INSERT OR IGNORE INTO extension_migrations VALUES ('analysis-reports',1);
            CREATE TABLE IF NOT EXISTS analyses (
                session_id TEXT NOT NULL REFERENCES sessions(session_id), end_ms INTEGER NOT NULL,
                data_json TEXT NOT NULL, PRIMARY KEY(session_id,end_ms));
            CREATE TABLE IF NOT EXISTS event_analyses (
                event_id TEXT NOT NULL REFERENCES events(event_id), session_id TEXT NOT NULL,
                end_ms INTEGER NOT NULL, PRIMARY KEY(event_id,session_id,end_ms),
                FOREIGN KEY(session_id,end_ms) REFERENCES analyses(session_id,end_ms));
            CREATE TABLE IF NOT EXISTS diagnostic_reports (
                event_id TEXT PRIMARY KEY REFERENCES events(event_id), data_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS detection_evidence (
                event_id TEXT NOT NULL REFERENCES events(event_id), kind TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL, data_json TEXT NOT NULL,
                PRIMARY KEY(event_id,kind,timestamp_ms));
            INSERT OR IGNORE INTO extension_migrations VALUES ('ai-event-status',1);
            CREATE TABLE IF NOT EXISTS event_ai_status (
                event_id TEXT PRIMARY KEY REFERENCES events(event_id), data_json TEXT NOT NULL);
            PRAGMA user_version=2;
        """)
        self.recover_interrupted()

    def __enter__(self) -> SQLiteRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def save_session(self, session_id: str, source: str) -> None:
        with self.connection:
            self._save_session(session_id, source)

    def _save_session(self, session_id: str, source: str) -> None:
        old = self.connection.execute(
            "SELECT source FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if old and old[0] != source:
            raise ValueError("Session source conflict")
        self.connection.execute(
            "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?)",
            (session_id, source, time.time_ns() // 1_000_000, "ACTIVE"),
        )

    def end_session(self, session_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE sessions SET status='STOPPED' WHERE session_id=?", (session_id,)
            )

    def _save_measurement(self, sample: Sample) -> None:
        data = serialize(sample.to_dict())
        previous = self.connection.execute(
            "SELECT data_json FROM measurements WHERE session_id=? AND sequence_number=?",
            (sample.session_id, sample.sequence_number),
        ).fetchone()
        if previous:
            if semantic_sample(json.loads(previous[0])) != semantic_sample(sample.to_dict()):
                raise ValueError("Conflicting sample identity")
            return  # retain the original raw bytes/first reception metadata
        self.connection.execute(
            "INSERT OR IGNORE INTO measurements VALUES (?,?,?,?)",
            (sample.session_id, sample.sequence_number, sample.timestamp_ms, data),
        )

    def save_measurement(self, sample: Sample) -> None:
        with self.connection:
            self._save_measurement(sample)

    def save_event(self, event: Event) -> None:
        if not event.samples or any(s.session_id != event.session_id for s in event.samples):
            raise ValueError("Event must have samples from exactly its own session")
        if event.status not in ("RECORDING", "COMPLETE", "PARTIAL"):
            raise ValueError("Unknown event status")
        with self.connection:
            first = event.samples[0]
            self._save_session(event.session_id, first.source.value)
            old = self.connection.execute(
                "SELECT * FROM events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            metadata = event_metadata(event)
            if old:
                old_meta = json.loads(old["metadata_json"])
                if old["session_id"] != event.session_id or serialize(
                    old_meta["trigger"]
                ) != serialize(metadata["trigger"]):
                    raise ValueError("Conflicting event identity")
                if old["status"] != "RECORDING":
                    existing = self.get_event(event.event_id)
                    if existing is None or semantic_event(existing) != semantic_event(event):
                        raise ValueError("Cannot overwrite finalized event")
                    return
            self.connection.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET "
                "status=excluded.status, metadata_json=excluded.metadata_json",
                (
                    event.event_id,
                    event.session_id,
                    event.trigger.timestamp_ms,
                    event.trigger.kind,
                    event.status,
                    serialize(metadata),
                ),
            )
            linked = self.connection.execute(
                "SELECT max(sequence_number) FROM event_samples WHERE event_id=?", (event.event_id,)
            ).fetchone()[0]
            for sample in event.samples:
                if linked is not None and sample.sequence_number <= linked:
                    if event.status != "RECORDING":
                        self._save_measurement(sample)
                    continue
                self._save_measurement(sample)
                self.connection.execute(
                    "INSERT OR IGNORE INTO event_samples VALUES (?,?,?)",
                    (event.event_id, sample.session_id, sample.sequence_number),
                )

    def get_event(self, event_id: str) -> Event | None:
        row = self.connection.execute(
            "SELECT metadata_json FROM events WHERE event_id=?", (event_id,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        rows = self.connection.execute(
            "SELECT m.data_json FROM measurements m JOIN event_samples e "
            "ON m.session_id=e.session_id AND m.sequence_number=e.sequence_number "
            "WHERE e.event_id=? ORDER BY m.timestamp_ms, m.sequence_number",
            (event_id,),
        ).fetchall()
        data["samples"] = [json.loads(r[0]) for r in rows]
        return Event.from_dict(data)

    def list_events(self) -> list[dict[str, Any]]:
        result = []
        for row in self.connection.execute(
            "SELECT event_id, session_id, trigger_ms, kind, status, metadata_json FROM events "
            "ORDER BY trigger_ms DESC, event_id"
        ):
            data = dict(row)
            metadata = json.loads(data.pop("metadata_json"))
            origin = metadata.get("origin")
            if origin is None:
                original = self.get_event(data["event_id"])
                origin = original.origin if original else "LIVE"
            data["origin"] = origin
            result.append(data)
        return result

    def save_simulation_run(self, session_id: str, metadata: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO simulation_runs VALUES (?,?)",
                (session_id, serialize(metadata)),
            )

    def get_simulation_run(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT metadata_json FROM simulation_runs WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(json.loads(row[0])) if row else None

    def save_analysis(self, result: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO analyses VALUES (?,?,?) ON CONFLICT(session_id,end_ms) "
                "DO UPDATE SET data_json=excluded.data_json",
                (result["session_id"], result["end_ms"], serialize(result)),
            )

    def link_analysis(self, event_id: str, session_id: str, end_ms: int) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO event_analyses VALUES (?,?,?)",
                (event_id, session_id, end_ms),
            )

    def get_event_analysis(self, event_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT a.data_json FROM analyses a JOIN event_analyses e "
            "ON a.session_id=e.session_id AND a.end_ms=e.end_ms WHERE e.event_id=? "
            "ORDER BY CASE WHEN json_extract(a.data_json,'$.decision')='ANOMALOUS' "
            "THEN 0 ELSE 1 END, a.end_ms LIMIT 1",
            (event_id,),
        ).fetchone()
        return dict(json.loads(row[0])) if row else None

    def get_analysis(self, session_id: str, end_ms: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT data_json FROM analyses WHERE session_id=? AND end_ms=?", (session_id, end_ms)
        ).fetchone()
        return dict(json.loads(row[0])) if row else None

    def get_event_analyses(self, event_id: str) -> list[dict[str, Any]]:
        """Every analysis linked to the event, oldest window first."""
        return [
            dict(json.loads(r[0]))
            for r in self.connection.execute(
                "SELECT a.data_json FROM analyses a JOIN event_analyses e "
                "ON a.session_id=e.session_id AND a.end_ms=e.end_ms WHERE e.event_id=? "
                "ORDER BY a.end_ms",
                (event_id,),
            )
        ]

    def save_event_ai_status(self, event_id: str, status: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO event_ai_status VALUES (?,?) ON CONFLICT(event_id) "
                "DO UPDATE SET data_json=excluded.data_json",
                (event_id, serialize(status)),
            )

    def get_event_ai_status(self, event_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT data_json FROM event_ai_status WHERE event_id=?", (event_id,)
        ).fetchone()
        return dict(json.loads(row[0])) if row else None

    def save_report(self, event_id: str, report: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO diagnostic_reports VALUES (?,?) ON CONFLICT(event_id) "
                "DO UPDATE SET data_json=excluded.data_json",
                (event_id, serialize(report)),
            )

    def save_detection(self, event_id: str, trigger: Any) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO detection_evidence VALUES (?,?,?,?)",
                (event_id, trigger.kind, trigger.timestamp_ms, serialize(asdict(trigger))),
            )

    def get_detections(self, event_id: str) -> list[dict[str, Any]]:
        return [
            json.loads(r[0])
            for r in self.connection.execute(
                "SELECT data_json FROM detection_evidence WHERE event_id=? "
                "ORDER BY timestamp_ms,kind",
                (event_id,),
            )
        ]

    def recover_interrupted(self) -> None:
        rows = self.connection.execute(
            "SELECT event_id FROM events WHERE status='RECORDING'"
        ).fetchall()
        with self.connection:
            for row in rows:
                event = self.get_event(row[0])
                if event:
                    event.status = "PARTIAL"
                    event.end_ms = event.samples[-1].timestamp_ms
                    event.limitations.append(
                        "استُعيد تسجيل غير مكتمل بعد توقف سابق؛ البيانات بعد الحدث جزئية"
                    )
                    metadata = event_metadata(event)
                    self.connection.execute(
                        "UPDATE events SET status='PARTIAL', metadata_json=? WHERE event_id=?",
                        (serialize(metadata), event.event_id),
                    )
            self.connection.execute(
                "UPDATE sessions SET status='INTERRUPTED' WHERE status='ACTIVE'"
            )

    def export_session(self, session_id: str, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for row in self.connection.execute(
                "SELECT data_json FROM measurements WHERE session_id=? ORDER BY timestamp_ms",
                (session_id,),
            ):
                stream.write(row[0] + "\n")
