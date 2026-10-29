"""Queue commands cross the thread boundary; the SQLite connection never does."""

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from doctorcar.analysis import status as ai
from doctorcar.core.interfaces import DataSource
from doctorcar.core.models import Sample
from doctorcar.core.sensor_registry import NUMERIC_IDS
from doctorcar.core.session import Session
from doctorcar.diagnostics.human_report import (
    build_report_model,
    load_ai_context,
    render_simple,
    render_technical,
)
from doctorcar.monitoring.evidence_rules import RULES, valid_value
from doctorcar.monitoring.simulation_evaluation import compare_schedule
from doctorcar.sources.device_simulator import SimulatedDeviceSource
from doctorcar.sources.faults import FaultInstance
from doctorcar.sources.network_device import NetworkDeviceSource
from doctorcar.sources.replay import ReplaySource
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.serial_device import ProtocolFileSource, SerialDeviceSource
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository

LOG = logging.getLogger(__name__)


def create_source(args: dict[str, Any]) -> DataSource:
    kind = args["source"]
    if kind == "simulation":
        return SimulationSource(
            args.get("scenario", "normal"),
            seed=int(args.get("seed", 42)),
            mode=args.get("mode"),
            faults=tuple(FaultInstance(**f) for f in args.get("faults", [])),
            max_faults=int(args.get("max_faults", 3)),
            normal_probability=float(args.get("normal_probability", 0.25)),
            scenario_family=args.get("scenario_family", "legacy"),
            scenarios=tuple(ScenarioInstance(**s) for s in args.get("scenarios", [])),
        )
    if kind == "device_simulator":
        return SimulatedDeviceSource(seed=int(args.get("seed", 42)))
    if kind == "replay":
        return ReplaySource(Path(args["path"]))
    if kind == "protocol_file":
        return ProtocolFileSource(Path(args["path"]))
    if kind == "serial":
        return SerialDeviceSource(args["port"])
    if kind == "network":
        return NetworkDeviceSource(
            args.get("host", "127.0.0.1"), int(args.get("network_port", 8765))
        )
    raise ValueError("مصدر غير متاح")


def presentation_rows(repo: SQLiteRepository) -> list[dict[str, Any]]:
    rows = repo.list_events()
    for row in rows:
        kinds = [d["kind"] for d in repo.get_detections(row["event_id"])]
        ml = "ML_ANOMALY" in kinds or row["kind"] == "ML_ANOMALY"
        rules = any(k != "ML_ANOMALY" for k in kinds) or row["kind"] != "ML_ANOMALY"
        row["detection_method"] = "RULE + ML" if ml and rules else "ML" if ml else "RULE"
        status = repo.get_event_ai_status(row["event_id"])
        row["ai_state"] = status["state"] if status else ai.NOT_RECORDED
        rule = RULES.get(row["kind"])
        if rule:
            event = repo.get_event(row["event_id"])
            row.update(
                system_ar=rule.system_ar,
                system_en=rule.system_en,
                support_count=len(event.trigger.evidence) if event else 0,
                checks_ar="؛ ".join(c[0] for c in rule.checks),
                checks_en="; ".join(c[1] for c in rule.checks),
            )
    return rows


def simulation_result(session: Session, repo: SQLiteRepository) -> dict[str, Any] | None:
    metadata = session.source.get_simulation_metadata()
    if metadata is None or session.last_sample is None:
        return None
    events = [r for r in repo.list_events() if r["session_id"] == session.last_sample.session_id]
    details = (
        {
            r["event_id"]: event
            for r in events
            if (event := repo.get_event(r["event_id"])) is not None
        }
        if metadata.get("scenario_family") == "multisensor"
        else None
    )
    return compare_schedule(metadata, events, session.last_sample.timestamp_ms, details)


def friendly_error(exc: BaseException) -> str:
    """User-facing text for a failed operation; the raw exception stays in the application log."""
    text = str(exc)
    if any("؀" <= ch <= "ۿ" for ch in text):
        return text  # already written for the user
    if isinstance(exc, FileNotFoundError):
        name = Path(str(exc.filename)).name if exc.filename else ""
        return f"الملف غير موجود: {name}".strip()
    if isinstance(exc, PermissionError):
        return "لا تتوفر صلاحية الوصول إلى الملف أو المنفذ المحدد"
    if isinstance(exc, IsADirectoryError):
        return "المسار المحدد ليس ملفًا"
    if "does not appear to be an IPv4 or IPv6 address" in text:
        return "عنوان الشبكة غير صالح؛ أدخل عنوان IPv4 مثل 127.0.0.1"
    if "loopback" in text.lower() or "LAN is disabled" in text:
        return "الاتصال الشبكي التجريبي يقبل العنوان المحلي 127.0.0.1 فقط"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "تعذر الاتصال بالجهاز أو المنفذ؛ تأكد أنه يعمل وأن العنوان صحيح"
    if isinstance(exc, ValueError):
        return "الملف أو الإعدادات المحددة غير صالحة؛ التفاصيل في سجل التطبيق"
    return "خطأ غير متوقع؛ التفاصيل في سجل التطبيق"


class BackendWorker(QThread):
    snapshot = Signal(object)
    events_changed = Signal(object)
    report_ready = Signal(str)
    simple_report_ready = Signal(str)
    status_changed = Signal(str)
    error = Signal(str)
    initialized = Signal()
    verification_changed = Signal(object)
    ports_changed = Signal(object)
    device_changed = Signal(object)
    simulation_changed = Signal(object)
    running_changed = Signal(bool)
    ai_changed = Signal(object)
    plot_ready = Signal(object)
    session_stats = Signal(object)

    def __init__(self, database: Path) -> None:
        super().__init__()
        self.database = database
        self.commands: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=32)
        self.shutdown_requested = threading.Event()
        self.starts = 0

    def submit(self, command: str, **arguments: Any) -> None:
        try:
            self.commands.put_nowait((command, arguments))
        except queue.Full:
            self.error.emit("قائمة الطلبات مشغولة؛ انتظر اكتمال الطلب الحالي")

    def shutdown(self) -> None:
        self.shutdown_requested.set()

    def run(self) -> None:
        session: Session | None = None
        repo: SQLiteRepository | None = None
        interval = 0.2
        next_poll = next_update = 0.0
        pending_snapshot: Sample | None = None
        try:
            repo = SQLiteRepository(self.database)
            self.events_changed.emit(presentation_rows(repo))
            self.initialized.emit()
            while not self.shutdown_requested.is_set():
                operation = "command"
                try:
                    try:
                        command, args = self.commands.get_nowait()
                    except queue.Empty:
                        command, args = "", {}
                    if command == "start":
                        if session is not None:
                            self.error.emit("توجد جلسة قائمة؛ أوقفها قبل بدء مصدر آخر")
                            continue
                        source = create_source(args)
                        pending_snapshot = None
                        analyzer = None
                        ai_failure = None
                        if args.get("ai_enabled", False):
                            try:
                                from doctorcar.analysis.analyzer import AnomalyAnalyzer

                                analyzer = AnomalyAnalyzer()
                            except Exception as exc:
                                # Rules and recording keep running; the reason stays visible.
                                ai_failure = f"{type(exc).__name__}: {exc}"
                                self.ai_changed.emit(
                                    {
                                        "decision": "UNAVAILABLE",
                                        "state": "MODEL_NOT_LOADED",
                                        "reason": ai_failure,
                                    }
                                )
                        session = Session(
                            source, repo, analyzer=analyzer, ai_failure=ai_failure, ml_alerts=False
                        )
                        session.start()
                        self.running_changed.emit(True)
                        self.starts += 1
                        interval = (
                            0.01
                            if args["source"] in ("serial", "network")
                            else 0.2 / float(args.get("speed", 1))
                        )
                        next_poll = 0
                        self.status_changed.emit(
                            "قيد التشغيل — " + source.get_capabilities().source
                        )
                    elif command == "stop" and session is not None:
                        self.session_stats.emit(
                            {"accepted": session.accepted, "rejected": session.rejected}
                        )
                        session.stop()
                        session = None
                        self.status_changed.emit("متوقف — القراءات المعروضة آخر بيانات مستلمة")
                        self.events_changed.emit(presentation_rows(repo))
                        self.running_changed.emit(False)
                    elif command == "ports":
                        self.ports_changed.emit(SerialDeviceSource.available_ports())
                    elif command == "verify":
                        if session is not None:
                            raise ValueError("Stop the active session before verification")
                        checking = create_source(args)
                        if isinstance(checking, SerialDeviceSource):
                            checking.verification_progress = self.status_changed.emit
                        self.verification_changed.emit(checking.verify())
                    elif command == "refresh":
                        self.events_changed.emit(presentation_rows(repo))
                    elif command == "report":
                        event = repo.get_event(args["event_id"])
                        if event:
                            analysis, status, later = load_ai_context(repo, event)
                            report = build_report_model(
                                event, analysis, repo.get_detections(event.event_id), status, later
                            )
                            repo.save_report(event.event_id, report.to_dict())
                            self.simple_report_ready.emit(
                                render_simple(report, args.get("language", "ar"))
                            )
                            self.plot_ready.emit(
                                {
                                    k: [[s.timestamp_ms, valid_value(s, k)] for s in event.samples]
                                    for k in NUMERIC_IDS
                                }
                            )
                        self.report_ready.emit(
                            render_technical(report, args.get("language", "ar"))
                            if event
                            else "الحدث غير موجود"
                        )
                    elif command == "export":
                        repo.export_session(args["session_id"], Path(args["path"]))
                        self.status_changed.emit("تم تصدير الجلسة إلى ملف Replay")
                    now = time.monotonic()
                    if session is not None and now >= next_poll:
                        operation = "poll"
                        result = session.step()
                        self.device_changed.emit(session.source.get_device_info())
                        if result is not None and result.accepted:
                            pending_snapshot = result.sample
                        if pending_snapshot is not None and now >= next_update:
                            self.ai_changed.emit(session.ai_status)
                            self.snapshot.emit(pending_snapshot)
                            self.session_stats.emit(
                                {"accepted": session.accepted, "rejected": session.rejected}
                            )
                            pending_snapshot = None
                            self.events_changed.emit(presentation_rows(repo))
                            evaluation = simulation_result(session, repo)
                            if evaluation is not None:
                                self.simulation_changed.emit(evaluation)
                            next_update = now + 0.12
                        next_poll = now + interval
                        if session.source.exhausted:
                            if session.last_sample:
                                self.snapshot.emit(session.last_sample)
                            self.session_stats.emit(
                                {"accepted": session.accepted, "rejected": session.rejected}
                            )
                            session.stop()
                            evaluation = simulation_result(session, repo)
                            if evaluation is not None:
                                self.simulation_changed.emit(evaluation)
                            session = None
                            self.status_changed.emit("اكتمل المصدر — آخر بيانات مستلمة")
                            self.events_changed.emit(presentation_rows(repo))
                            self.running_changed.emit(False)
                except Exception as exc:
                    LOG.exception("Backend operation failed")
                    self.error.emit(f"تعذر إكمال العملية: {friendly_error(exc)}")
                    if operation == "command" and command in (
                        "export",
                        "report",
                        "refresh",
                        "verify",
                        "ports",
                    ):
                        self.msleep(2)
                        continue
                    if session is not None:
                        self.device_changed.emit(session.source.get_device_info())
                        try:
                            try:
                                if isinstance(session.source, SerialDeviceSource) and isinstance(
                                    exc, (ConnectionError, TimeoutError, OSError)
                                ):
                                    session.record_connection_loss(str(exc))
                            finally:
                                session.stop()
                        except Exception:
                            LOG.exception("Session cleanup failed")
                        session = None
                    self.running_changed.emit(False)
                    self.status_changed.emit("خطأ — المصدر متوقف؛ البيانات ليست حية")
                self.msleep(2)
        except Exception:
            LOG.exception("Backend initialization failed")
            self.error.emit("تعذر فتح التخزين المحلي؛ تحقق من المسار وصلاحيات الكتابة")
        finally:
            try:
                if session is not None:
                    session.stop()
            except Exception:
                LOG.exception("Final cleanup failed")
            finally:
                if repo is not None:
                    repo.close()
