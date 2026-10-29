"""DC-UX-001 Gate 2: startup splash and launcher (real stages, failure paths, single main window)."""

# ruff: noqa: E501

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from doctorcar.ui.startup import Launcher  # noqa: E402


def pump(app, until, limit=30.0):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.005)
    return until()


def run_launcher(tmp_path, database, loader, timeout_s=30.0):
    app = QApplication.instance() or QApplication([])
    launcher = Launcher(app, database, ai_loader=loader, timeout_s=timeout_s, interactive=False)
    launcher.start()
    return app, launcher


def close(app, launcher):
    window = launcher.window
    if window is not None:
        window.close()
        pump(app, lambda: window.worker.isFinished(), 10)
    launcher.dispose()


def test_normal_startup_shows_splash_then_one_usable_window(tmp_path):
    app, launcher = run_launcher(tmp_path, tmp_path / "a.sqlite3", lambda: "iforest-test")
    try:
        assert launcher.splash is not None and launcher.splash.isVisible()
        assert [s[0] for s in launcher.splash.stages] == ["init", "settings", "db", "ai", "ui"]
        assert pump(app, lambda: launcher.finished_ok)
        assert launcher.window.isVisible() and launcher.window.backend_ready
        assert launcher.splash is None  # closed only once the window is usable
        assert launcher.windows_created == 1
        assert launcher.ai_state == "done" and launcher.ai_info == "iforest-test"
        # stage order is the order things really finished: db and ai finish before "ready"
        stages = launcher.timeline
        assert stages.index(("db", "done")) < stages.index(("ready", "done"))
        assert stages.index(("ai", "done")) < stages.index(("ready", "done"))
        assert "iforest-test" in launcher.window.about_ai.text()
    finally:
        close(app, launcher)


def test_ai_failure_does_not_block_startup(tmp_path):
    def broken() -> str:
        raise RuntimeError("model file corrupt")

    app, launcher = run_launcher(tmp_path, tmp_path / "b.sqlite3", broken)
    try:
        assert pump(app, lambda: launcher.finished_ok)
        assert launcher.ai_state == "failed"
        window = launcher.window
        assert window.isVisible() and window.backend_ready
        assert "unavailable" in window.ai_pill.text().lower() or "غير متاح" in window.ai_pill.text()
        assert window.start_button.isEnabled()  # rules and recording stay usable
    finally:
        close(app, launcher)


def test_unwritable_database_shows_failure_and_never_opens_window(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    app, launcher = run_launcher(tmp_path, blocker / "db.sqlite3", lambda: "v")
    failures: list[str] = []
    launcher.startup_failed.connect(failures.append)
    try:
        assert pump(app, lambda: bool(failures), 20)
        assert not launcher.finished_ok
        assert launcher.splash is not None and launcher.splash.failure
        assert not launcher.window.isVisible()
        assert launcher.db_state == "failed"
        shown = launcher.splash.failure
        assert "Errno" not in shown and "WinError" not in shown and str(blocker) not in shown
    finally:
        close(app, launcher)


def test_hung_ai_loader_times_out_instead_of_hanging_forever(tmp_path):
    release = {"go": False}

    def hang() -> str:
        end = time.monotonic() + 6
        while not release["go"] and time.monotonic() < end:
            time.sleep(0.05)
        return "late"

    app, launcher = run_launcher(tmp_path, tmp_path / "c.sqlite3", hang, timeout_s=1.0)
    failures: list[str] = []
    launcher.startup_failed.connect(failures.append)
    try:
        assert pump(app, lambda: bool(failures), 10)
        assert "مهلة" in failures[0] or "timed out" in failures[0]
        assert not launcher.finished_ok
        assert launcher.splash is not None and launcher.splash.failure
    finally:
        release["go"] = True
        close(app, launcher)


def test_path_with_arabic_letters_and_spaces(tmp_path):
    folder = tmp_path / "مجلد التجربة 1"
    folder.mkdir()
    app, launcher = run_launcher(tmp_path, folder / "قاعدة بيانات.sqlite3", lambda: "v")
    try:
        assert pump(app, lambda: launcher.finished_ok)
        assert (folder / "قاعدة بيانات.sqlite3").exists()
        assert launcher.windows_created == 1
    finally:
        close(app, launcher)


def test_restart_after_failure_still_creates_only_one_window(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    app, launcher = run_launcher(tmp_path, blocker / "db.sqlite3", lambda: "v")
    try:
        assert pump(app, lambda: launcher.db_state == "failed", 20)
        launcher.restart(tmp_path / "good.sqlite3")
        assert pump(app, lambda: launcher.finished_ok, 20)
        assert launcher.windows_created == 1
        assert launcher.window.isVisible()
    finally:
        close(app, launcher)


@pytest.mark.parametrize("language", ["ar", "en"])
def test_splash_stage_names_follow_saved_language(tmp_path, language):
    from PySide6.QtCore import QSettings

    db = tmp_path / "l.sqlite3"
    QSettings(str(db.with_suffix(".settings.ini")), QSettings.Format.IniFormat).setValue(
        "language", language
    )
    app, launcher = run_launcher(tmp_path, db, lambda: "v")
    try:
        names = [text for _, text, _ in launcher.splash.stages]
        assert (names[0] == "تهيئة التطبيق") == (language == "ar")
        assert pump(app, lambda: launcher.finished_ok)
    finally:
        close(app, launcher)


def test_launcher_reads_saved_theme_before_showing_splash(tmp_path):
    from PySide6.QtCore import QSettings

    db = tmp_path / "t.sqlite3"
    QSettings(str(db.with_suffix(".settings.ini")), QSettings.Format.IniFormat).setValue(
        "theme", "dark"
    )
    app, launcher = run_launcher(tmp_path, Path(db), lambda: "v")
    try:
        assert launcher.splash.theme == "dark"
        assert pump(app, lambda: launcher.finished_ok)
    finally:
        close(app, launcher)
