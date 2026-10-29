"""The sole source-to-storage orchestration path shared by GUI, CLI and tests."""

from dataclasses import replace
from typing import Any

from doctorcar.analysis import status as ai
from doctorcar.core.interfaces import DataSource
from doctorcar.core.models import Event, Sample, Trigger
from doctorcar.monitoring.data_quality import DataQualityValidator, ValidationResult
from doctorcar.monitoring.event_detector import RULE_VERSION, EventDetector
from doctorcar.monitoring.event_recorder import EventRecorder
from doctorcar.storage.sqlite_repository import SQLiteRepository


class Session:
    def __init__(
        self,
        source: DataSource,
        repository: SQLiteRepository,
        *,
        analyzer: Any = None,
        ai_failure: str | None = None,
        ml_alerts: bool = True,
    ) -> None:
        self.source, self.repository = source, repository
        # False = advisory ML (DEF-001): an ML-only anomaly never opens its own event; it is kept
        # as an analysis, counted in `advisory_ml`, and supports an event a rule has opened.
        self.ml_alerts = ml_alerts
        self.advisory_ml: list[dict[str, Any]] = []
        self.validator = DataQualityValidator()
        self.detector = EventDetector()
        self.recorder = EventRecorder(repository)
        self.running = False
        self.last_sample: Sample | None = None
        self.accepted = 0
        self.rejected = 0
        self.analyzer = analyzer
        # Why AI is not analyzing: a load failure is reported as such, never as "disabled".
        self.ai_failure = ai_failure
        self.ai_state = (
            ai.ANALYZED_NORMAL
            if analyzer is not None
            else (ai.MODEL_NOT_LOADED if ai_failure else ai.DISABLED)
        )
        self.ai_status: dict[str, Any] = (
            {"decision": "INSUFFICIENT_DATA", "reason": "waiting for the first window"}
            if analyzer is not None
            else {
                "decision": "UNAVAILABLE",
                "reason": ai_failure or "disabled",
                "state": self.ai_state,
            }
        )

    def start(self) -> None:
        if self.running:
            raise RuntimeError("A session is already running")
        try:
            self.source.connect()
            self.source.start()
            self.validator = DataQualityValidator()
            self.detector = EventDetector()
            self.recorder = EventRecorder(self.repository)
            self.last_sample = None
            self.accepted = self.rejected = 0
            self.running = True
        except Exception:
            self.source.disconnect()
            raise

    def step(self) -> ValidationResult | None:
        if not self.running:
            return None
        sample = self.source.read_measurements()
        for imported in self.source.drain_events():
            event_validator = DataQualityValidator()
            normalized = []
            for event_sample in imported.samples:
                validated = event_validator.validate_measurement(event_sample)
                if not validated.accepted:
                    raise ValueError("Imported event has invalid sample ordering")
                normalized.append(validated.sample)
            self.repository.save_event(replace(imported, samples=normalized))
            self.repository.save_event_ai_status(
                imported.event_id,
                {
                    "state": ai.HISTORICAL,
                    "reason": "imported from device history; not analyzed live",
                    "detection_ms": imported.trigger.timestamp_ms,
                },
            )
        if sample is None:
            return None
        if self.last_sample and self.last_sample.session_id != sample.session_id:
            self.recorder.stop()
            self.repository.end_session(self.last_sample.session_id)
            self.validator = DataQualityValidator()
            self.detector = EventDetector()
            self.recorder = EventRecorder(self.repository)
            self.last_sample = None
        result = self.validator.validate_measurement(sample, self.source.get_current_timestamp_ms())
        if not result.accepted:
            self.rejected += 1
            return result
        self.repository.save_session(sample.session_id, sample.source.value)
        if self.last_sample is None:
            metadata = self.source.get_simulation_metadata()
            if metadata is not None:
                self.repository.save_simulation_run(sample.session_id, metadata)
        self.repository.save_measurement(result.sample)
        triggers = self.detector.evaluate_trigger(result.sample, result.issues)
        rule_triggers = triggers
        analysis = None
        ml_trigger = None
        if self.analyzer is not None:
            try:
                analysis, ml_trigger = self.analyzer.push(result.sample)
                if analysis is not None:
                    self.ai_status = analysis
                    self.repository.save_analysis(analysis)
            except Exception as exc:
                # Rules and recording continue; every later event states the technical failure.
                self.ai_failure, self.ai_state, self.analyzer = str(exc), ai.INFERENCE_FAILED, None
                self.ai_status = {
                    "decision": "UNAVAILABLE",
                    "reason": str(exc),
                    "state": ai.INFERENCE_FAILED,
                }
        # One recorder. Nearby rule/ML detections support one event; quality stays separate.
        nearby = [
            e
            for e in self.recorder.active.values()
            if e.trigger.kind != "DATA_QUALITY"
            and 0 <= sample.timestamp_ms - e.trigger.timestamp_ms <= 10000
        ]
        if (
            ml_trigger is not None
            and not nearby
            and not any(t.kind != "DATA_QUALITY" for t in triggers)
        ):
            if self.ml_alerts:
                triggers += (ml_trigger,)
            else:
                self.advisory_ml.append(
                    {"timestamp_ms": ml_trigger.timestamp_ms, "reason": ml_trigger.reason}
                )
        if any(e.trigger.kind == "ML_ANOMALY" for e in nearby):
            triggers = tuple(t for t in triggers if t.kind == "DATA_QUALITY")
        known = set(self.recorder.active)
        completed = self.recorder.append_measurement(result.sample, triggers)
        for event in [e for i, e in self.recorder.active.items() if i not in known]:
            self._record_ai_status(event)
        for trigger in rule_triggers + ((ml_trigger,) if ml_trigger else ()):
            targets = [
                e
                for e in self.recorder.active.values()
                if e.trigger.kind == trigger.kind and e.trigger.timestamp_ms == trigger.timestamp_ms
            ]
            if not targets and trigger.kind != "DATA_QUALITY":
                targets = nearby[:1]
                if not targets and trigger.kind == "ML_ANOMALY":
                    targets = [
                        e
                        for e in self.recorder.active.values()
                        if e.trigger.timestamp_ms == sample.timestamp_ms
                        and e.trigger.kind != "DATA_QUALITY"
                    ][:1]
            for target in targets:
                self.repository.save_detection(target.event_id, trigger)
        if analysis is not None and analysis.get("decision") == "ANOMALOUS":
            # A later anomalous window supports nearby events but never rewrites what was known
            # at detection; it is linked as a separate, later analysis.
            for event in nearby:
                if analysis["end_ms"] > event.trigger.timestamp_ms:
                    self._ensure_xai(analysis)
                    self.repository.link_analysis(
                        event.event_id, sample.session_id, analysis["end_ms"]
                    )
        self.last_sample = result.sample
        self.accepted += 1
        for event in completed:
            self._save_report(event.event_id)
        return result

    def _ensure_xai(self, analysis: dict[str, Any]) -> None:
        """Explain only anomalous decisions, from the exact model and window that produced them."""
        if "xai" in analysis or self.analyzer is None:
            return
        try:
            analysis["xai"] = self.analyzer.explain(analysis)
        except Exception as exc:
            analysis["xai"] = {"status": "UNAVAILABLE", "reason": str(exc)}
        self.repository.save_analysis(analysis)

    def _record_ai_status(self, event: Event) -> None:
        """Link the newest valid analysis known at detection time, or record why none exists."""
        detection = event.trigger.timestamp_ms
        status: dict[str, Any] = {"detection_ms": detection}
        if self.analyzer is None:
            status.update(state=self.ai_state, reason=self.ai_failure or "AI analysis not enabled")
        else:
            status["model_version"] = self.analyzer.model.metadata["model_version"]
            status["max_age_ms"] = self.analyzer.max_age_ms
            analysis = self.analyzer.latest_before(event.session_id, detection)
            if analysis is not None and not (
                analysis.get("session_id", event.session_id) == event.session_id
                and 0 <= detection - analysis["end_ms"] <= self.analyzer.max_age_ms
            ):
                # Defence in depth (DEF-012): the age/causality limit is enforced here as well,
                # so a different or stubbed analyzer cannot link a stale or future window.
                analysis = None
            if analysis is None:
                status.update(
                    state=ai.NO_RECENT_ANALYSIS,
                    reason=f"no analysis window ended within {self.analyzer.max_age_ms} ms "
                    "before the detection",
                )
            elif analysis["decision"] == "INSUFFICIENT_DATA":
                status.update(
                    state=ai.INSUFFICIENT_DATA,
                    reason=analysis.get("reason", "insufficient data"),
                    window_end_ms=analysis["end_ms"],
                )
            else:
                anomalous = analysis["decision"] == "ANOMALOUS"
                if anomalous:
                    self._ensure_xai(analysis)
                self.repository.link_analysis(event.event_id, event.session_id, analysis["end_ms"])
                status.update(
                    state=ai.ANALYZED_ANOMALOUS if anomalous else ai.ANALYZED_NORMAL,
                    window_start_ms=analysis["start_ms"],
                    window_end_ms=analysis["end_ms"],
                    age_ms=detection - analysis["end_ms"],
                    score=analysis["score"],
                    threshold=analysis["threshold"],
                    model_version=analysis["model_version"],
                    model_sha256=analysis["model_sha256"],
                )
        self.repository.save_event_ai_status(event.event_id, status)

    def _save_report(self, event_id: str) -> None:
        from doctorcar.diagnostics.human_report import build_report_model, load_ai_context

        event = self.repository.get_event(event_id)
        if event:
            analysis, status, later = load_ai_context(self.repository, event)
            self.repository.save_report(
                event_id,
                build_report_model(
                    event, analysis, self.repository.get_detections(event_id), status, later
                ).to_dict(),
            )

    def record_connection_loss(self, reason: str) -> None:
        if self.last_sample:
            trigger = Trigger(
                "CONNECTION",
                "انقطع مصدر البيانات",
                reason,
                RULE_VERSION,
                self.last_sample.timestamp_ms,
            )
            self._record_ai_status(self.recorder.start_event(self.last_sample, trigger))

    def stop(self) -> None:
        try:
            pending = list(self.recorder.active)
            self.recorder.stop()
            for event_id in pending:
                self._save_report(event_id)
            if self.last_sample:
                self.repository.end_session(self.last_sample.session_id)
        finally:
            self.running = False
            try:
                self.source.stop()
            finally:
                self.source.disconnect()
