"""Startup orchestration: splash window, real stages, main window creation.

Heavy work stays off the GUI thread: the database opens in BackendWorker and the AI model is
verified/loaded by ``AIWarmup`` (which also pre-imports scikit-learn so the first monitoring
session starts quickly). The splash closes only when the main window is actually usable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from doctorcar.ui.localization import translate
from doctorcar.ui.splash import SplashWindow

LOG = logging.getLogger(__name__)

STAGE_TEXT = {
    "ar": {
        "init": "تهيئة التطبيق",
        "settings": "تحميل الإعدادات",
        "db": "تجهيز قاعدة البيانات",
        "ai": "تحميل نموذج الذكاء الاصطناعي",
        "ui": "إعداد الواجهة",
        "ready": "جاهز للتشغيل",
    },
    "en": {
        "init": "Initializing application",
        "settings": "Loading settings",
        "db": "Preparing the database",
        "ai": "Loading the AI model",
        "ui": "Building the interface",
        "ready": "Ready",
    },
}


def default_ai_loader() -> str:
    """Verify and load the default model; returns its version. Raises when it cannot be loaded."""
    from doctorcar.analysis.analyzer import AnomalyAnalyzer

    analyzer = AnomalyAnalyzer()
    return str(analyzer.model.metadata["model_version"])


class AIWarmup(QThread):
    loaded = Signal(str)
    failed = Signal(str)

    def __init__(self, loader: Callable[[], str]) -> None:
        super().__init__()
        self._loader = loader

    def run(self) -> None:
        try:
            self.loaded.emit(self._loader())
        except Exception as exc:  # the application keeps working without ML
            LOG.exception("AI model could not be loaded at startup")
            self.failed.emit(f"{type(exc).__name__}")


class Launcher(QObject):
    """Creates exactly one main window and closes the splash when it is usable."""

    ready = Signal(object)
    startup_failed = Signal(str)

    def __init__(
        self,
        app: QApplication,
        database: Path,
        *,
        use_splash: bool = True,
        ai_loader: Callable[[], str] = default_ai_loader,
        timeout_s: float = 30.0,
        interactive: bool = True,
    ) -> None:
        super().__init__()
        self.app, self.database, self.use_splash = app, database, use_splash
        self.ai_loader, self.timeout_s, self.interactive = ai_loader, timeout_s, interactive
        self.window: Any = None
        self.splash: SplashWindow | None = None
        self.warmup: AIWarmup | None = None
        self.db_state = self.ai_state = self.ui_state = "pending"
        self.ai_info = ""
        self.windows_created = 0
        self.timeline: list[tuple[str, str]] = []  # (stage, event) as it really happened
        self.language = "ar"
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._on_timeout)
        self.finished_ok = False

    # ------------------------------------------------------------------ flow
    def start(self) -> None:
        self.db_state = self.ai_state = self.ui_state = "pending"
        self.finished_ok = False
        self.app.setQuitOnLastWindowClosed(False)  # closing the splash must never end the process
        theme, language = self._read_preferences()
        self.language = language
        texts = STAGE_TEXT.get(language, STAGE_TEXT["en"])
        if self.use_splash:
            self.splash = SplashWindow(theme, language)
            for key in ("init", "settings", "db", "ai", "ui"):
                self.splash.add_stage(key, texts[key])
            self.splash.show()
            self.app.processEvents()
        self._stage("init", "done")
        self._stage("settings", "done")
        self._stage("db", "running")
        self._stage("ai", "running")
        self.warmup = AIWarmup(self.ai_loader)
        self.warmup.loaded.connect(self._on_ai_loaded)
        self.warmup.failed.connect(self._on_ai_failed)
        self.warmup.start()
        self.timeout.start(int(self.timeout_s * 1000))
        QTimer.singleShot(0, self._build_window)

    def _read_preferences(self) -> tuple[str, str]:
        try:
            settings = QSettings(
                str(self.database.resolve().with_suffix(".settings.ini")),
                QSettings.Format.IniFormat,
            )
            return str(settings.value("theme", "light")), str(settings.value("language", "ar"))
        except Exception:
            return "light", "ar"

    def _build_window(self) -> None:
        from doctorcar.ui.main_window import MainWindow

        self._stage("ui", "running")
        if self.windows_created:  # never a second main window
            return
        try:
            window = MainWindow(self.database)
        except Exception as exc:
            LOG.exception("Main window could not be created")
            self._fail(f"{type(exc).__name__}: {exc}")
            return
        self.windows_created += 1
        self.window = window
        window.worker.initialized.connect(self._on_db_ready)
        window.worker.error.connect(self._on_worker_error)
        self._stage("ui", "done")
        self._check_ready()

    # ------------------------------------------------------------------ callbacks
    def _on_db_ready(self) -> None:
        self._stage("db", "done")
        self._check_ready()

    def _on_worker_error(self, message: str) -> None:
        if self.db_state != "done" and not self.finished_ok:
            self._stage("db", "failed")
            self._fail(message)

    def _on_ai_loaded(self, version: str) -> None:
        self.ai_info = version
        self._stage("ai", "done")
        self._check_ready()

    def _on_ai_failed(self, reason: str) -> None:
        self.ai_info = reason
        self._stage("ai", "failed")
        self._check_ready()

    def _on_timeout(self) -> None:
        if not self.finished_ok:
            ar = self.language == "ar"
            self._fail(
                "انتهت مهلة بدء التشغيل؛ أغلق البرنامج وحاول مجددًا"
                if ar
                else "Startup timed out; close the program and try again"
            )

    def _stage(self, key: str, state: str) -> None:
        if key == "db":
            self.db_state = state
        elif key == "ai":
            self.ai_state = state
        elif key == "ui":
            self.ui_state = state
        self.timeline.append((key, state))
        if self.splash is not None:
            if state == "running":
                self.splash.start_stage(key)
            else:
                self.splash.finish_stage(key, state == "done")
            self.app.processEvents()

    def _check_ready(self) -> None:
        if self.finished_ok or self.window is None:
            return
        if "pending" in (self.db_state, self.ai_state, self.ui_state):
            return
        if "running" in (self.db_state, self.ai_state, self.ui_state):
            return
        if self.db_state != "done":
            return
        self.finished_ok = True
        self.timeout.stop()
        self.window.attach_startup_result(self.ai_state == "done", self.ai_info)
        self.app.setQuitOnLastWindowClosed(True)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.timeline.append(("ready", "done"))
        if self.splash is not None:
            self.splash.close()
            self.splash = None
        self.ready.emit(self.window)

    # ------------------------------------------------------------------ failure path
    def _fail(self, message: str) -> None:
        if self.finished_ok:
            return
        self.timeout.stop()
        LOG.error("Startup failed: %s", message)
        message = translate(message, self.language)
        self.timeline.append(("startup", "failed"))
        if self.splash is not None:
            self.splash.show_failure(message)
        self.startup_failed.emit(message)
        if self.interactive:
            QTimer.singleShot(0, lambda: self._ask_recovery(message))

    def _ask_recovery(self, message: str) -> None:
        ar = self.language == "ar"
        box = QMessageBox(self.splash)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("DoctorCAR")
        box.setText(
            "تعذر فتح قاعدة البيانات المحلية." if ar else "The local database could not be opened."
        )
        box.setInformativeText(
            (
                "تحقق من المسار وصلاحيات الكتابة. يمكنك اختيار ملف قاعدة بيانات آخر أو الإغلاق.\n\n"
                if ar
                else "Check the path and write permissions. You can choose another database file or quit.\n\n"
            )
            + message
        )
        choose = box.addButton(
            "اختيار ملف آخر" if ar else "Choose another file", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton("إغلاق" if ar else "Quit", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is choose:
            path, _ = QFileDialog.getSaveFileName(
                self.splash,
                "DoctorCAR",
                str(self.database),
                "SQLite (*.sqlite3)",
                options=QFileDialog.Option.DontUseNativeDialog,
            )
            if path:
                self.restart(Path(path))
                return
        self.dispose()
        self.app.quit()

    def restart(self, database: Path) -> None:
        self.dispose()
        self.database = database
        self.windows_created = 0
        self.start()

    def dispose(self) -> None:
        if self.splash is not None:
            self.splash.close()
            self.splash = None
        if self.window is not None and not self.finished_ok:
            self.window.worker.shutdown()
            self.window.worker.wait(3000)
            self.window.closing = False
            self.window.age_timer.stop()
            self.window.deleteLater()
            self.window = None
        if self.warmup is not None:
            self.warmup.wait(5000)
