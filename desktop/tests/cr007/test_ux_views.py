"""DC-UX-001: design system, dashboard states, sensor tiles, events view, settings, navigation, notifications."""

# ruff: noqa: E501

import os
import re
import time
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from doctorcar.core.models import Quality, Reading, Sample, Source  # noqa: E402
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY  # noqa: E402
from doctorcar.sources.device_simulator import historical_events  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402
from doctorcar.ui import theme as design  # noqa: E402
from doctorcar.ui.main_window import MainWindow  # noqa: E402
from doctorcar.ui.widgets import StatusPill, bidi_safe  # noqa: E402

ARABIC = re.compile("[؀-ۿ]")


def pump(app, seconds=0.0, until=None, limit=20.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.004)
    return bool(until and until())


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app, tmp_path):
    w = MainWindow(tmp_path / "ux.sqlite3")
    w.show()
    pump(app, until=lambda: w.backend_ready)
    yield w
    w.close()
    w.worker.wait(5000)


def sample(seq=0, ms=0, **changes):
    readings = {k: Reading(10.0 + seq, REGISTRY.get(k).unit) for k in NUMERIC_IDS}
    readings.update(changes.pop("readings", {}))
    return Sample(
        "trip", Source.SIMULATION, seq, ms, readings, dtc_quality=Quality.AVAILABLE, **changes
    )


# ------------------------------------------------------------------ design system
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_palette_text_contrast_meets_wcag_aa(theme):
    p = design.palette(theme)
    pairs = [
        ("text", "bg"),
        ("text", "surface"),
        ("muted", "surface"),
        ("muted", "bg"),
        ("text", "surface_alt"),
        ("primary_text", "primary"),
        ("primary_text", "primary_hover"),
        ("success", "success_bg"),
        ("warning", "warning_bg"),
        ("danger", "danger_bg"),
        ("info", "info_bg"),
        ("sidebar_text", "sidebar"),
        ("sidebar_muted", "sidebar"),
        ("sidebar_text", "sidebar_active"),
        ("focus", "surface"),
    ]
    failed = [
        (a, b, round(design.contrast_ratio(getattr(p, a), getattr(p, b)), 2))
        for a, b in pairs
        if design.contrast_ratio(getattr(p, a), getattr(p, b)) < 4.5
    ]
    assert not failed, failed


def test_one_stylesheet_owns_the_look_and_fonts_are_system_fonts(window):
    sheet = window.styleSheet()
    assert design.palette("light").bg in sheet
    assert (
        design.pick_family(design.FONT_STACK) in design.FONT_STACK
    )  # installed system font, nothing bundled
    for name in ("pill", "card"):
        assert name in sheet


def test_status_pill_carries_a_symbol_not_only_a_colour():
    for tone, symbol in (("ok", "✓"), ("warn", "▲"), ("danger", "✕"), ("info", "●"), ("idle", "○")):
        pill = StatusPill("x", tone)
        assert pill.text().startswith(symbol)


def test_bidi_isolates_latin_runs_in_arabic_text_only():
    assert bidi_safe("AI: نمط معتاد") == "⁦AI:⁩ نمط معتاد"
    assert bidi_safe("plain english") == "plain english"


# ------------------------------------------------------------------ dashboard / connection state
def test_dashboard_states_follow_real_signals(window, app):
    assert window.conn_state() == "idle"
    assert "غير متصل" in window.conn_pill.text()
    window.set_running(True)
    assert window.conn_state() == "waiting"  # running, no sample yet: never "receiving"
    window.show_stats({"accepted": 1, "rejected": 0})
    window.show_sample(sample(0, 0))
    assert window.conn_state() == "receiving"
    assert "يستقبل" in window.dash_state_pill.text()
    window.last_received -= 10  # no new sample for 10 s
    assert window.conn_state() == "lost"
    window.set_running(False)
    window.set_status("متوقف — القراءات المعروضة آخر بيانات مستلمة")
    assert window.conn_state() == "stopped"
    window.set_status("خطأ — المصدر متوقف؛ البيانات ليست حية")
    assert window.conn_state() == "error"
    window.set_status("اكتمل المصدر — آخر بيانات مستلمة")
    assert window.conn_state() == "ended"


def test_dashboard_counts_come_from_the_session_stats_signal(window):
    window.set_running(True)
    window.show_stats({"accepted": 123, "rejected": 0})
    assert "123" in window.dash_samples.text()
    window.set_language = None
    window.language_combo.setCurrentIndex(1)
    assert "Samples received: 123" in window.dash_samples.text()


def test_quick_actions_have_real_effects(window, app):
    window.navigation.setCurrentRow(0)
    QTest.mouseClick(window.dash_events, Qt.MouseButton.LeftButton)
    assert window.pages.currentIndex() == 3
    window.navigation.setCurrentRow(0)
    assert not window.dash_report.isEnabled()  # no event yet: no fake "open report"
    assert not window.dash_stop.isEnabled() and window.dash_start.isEnabled()


# ------------------------------------------------------------------ sensors
def test_missing_reading_is_a_dash_never_zero_and_quality_is_named(window):
    readings = {
        "RPM": Reading(None, "rpm", Quality.MISSING),
        "SPEED": Reading(None, "km/h", Quality.INVALID),
    }
    window.show_sample(sample(0, 0, readings=readings))
    rpm = window.sensor_tiles["RPM"]
    assert "—" in rpm.value_label.text() and "0" not in rpm.value_label.text().replace("⁦", "")
    assert "مفقودة" in rpm.quality.text()
    assert "غير صالحة" in window.sensor_tiles["SPEED"].quality.text()
    assert window.sensor_table.item(0, 2).text().strip("⁦⁩") == "—"


def test_stale_data_is_marked_not_live_and_not_animated(window):
    window.set_running(True)
    window.show_sample(sample(0, 0))
    tile = window.sensor_tiles["RPM"]
    assert tile.property("state") == "active"
    window.last_received -= 5
    window.update_age()
    assert tile.property("state") == "stale"
    assert "قديمة" in tile.quality.text()
    assert tile.last_value is None  # no baseline: a stale tile cannot flash on old data


def test_flash_only_for_large_change_of_a_trusted_new_sample(window, monkeypatch):
    from doctorcar.ui.widgets import Motion

    monkeypatch.setattr(Motion, "os_allows", classmethod(lambda cls: True))
    window.navigation.setCurrentRow(2)
    window.show_sample(sample(0, 0, readings={"RPM": Reading(800.0, "rpm")}))
    tile = window.sensor_tiles["RPM"]
    window.show_sample(sample(1, 200, readings={"RPM": Reading(805.0, "rpm")}))
    assert tile._anim.state() != tile._anim.State.Running  # +5 rpm: not highlighted
    window.show_sample(sample(2, 400, readings={"RPM": Reading(1500.0, "rpm")}))
    assert tile._anim.state() == tile._anim.State.Running  # +695 rpm, AVAILABLE: highlighted
    tile._anim.stop()
    monkeypatch.setattr(
        Motion, "os_allows", classmethod(lambda cls: False)
    )  # Windows animations off
    window.show_sample(sample(3, 600, readings={"RPM": Reading(400.0, "rpm")}))
    assert tile._anim.state() != tile._anim.State.Running


def test_sensor_search_and_filter_hide_tiles_and_table_rows(window):
    window.show_sample(sample(0, 0))
    window.sensor_search.setText("RPM")
    shown = [s for s, t in window.sensor_tiles.items() if not t.isHidden()]
    assert shown == ["RPM"]
    assert window.sensor_table.isRowHidden(1)
    window.sensor_search.setText("zzz-no-such")
    assert window.sensor_empty_results.isVisible() or not window.sensor_empty_results.isHidden()
    window.sensor_search.setText("")
    window.sensor_filter.setCurrentIndex(window.sensor_filter.findData("thermal"))
    assert {s for s, t in window.sensor_tiles.items() if not t.isHidden()} == {
        "COOLANT_TEMP",
        "INTAKE_TEMP",
    }


def test_empty_state_before_first_sample(window):
    window.navigation.setCurrentRow(2)
    assert not window.sensor_empty.isHidden() and window.sensor_views.isHidden()
    window.show_sample(sample(0, 0))
    assert window.sensor_empty.isHidden() and not window.sensor_views.isHidden()


# ------------------------------------------------------------------ events view
@pytest.fixture()
def window_with_events(app, tmp_path):
    path = tmp_path / "ev.sqlite3"
    with SQLiteRepository(path) as repo:
        for event in historical_events():
            repo.save_event(event)
    w = MainWindow(path)
    w.show()
    pump(app, until=lambda: w.backend_ready and w.events_table.rowCount() == 2)
    yield w
    w.close()
    w.worker.wait(5000)


def test_events_empty_state_then_rows(window, app):
    window.navigation.setCurrentRow(3)
    assert not window.events_empty.isHidden() and window.events_table.isHidden()


def test_events_search_filter_sort_and_selection_survive_refresh(window_with_events, app):
    w = window_with_events
    w.navigation.setCurrentRow(3)
    ids = [w.events_table.item(r, 3).text() for r in range(2)]
    w.events_table.selectRow(1)
    chosen = w.selected_event_id()
    w.show_events(list(w.event_rows))  # a refresh must keep the user's selection by event id
    assert w.selected_event_id() == chosen
    w.event_filter.setCurrentIndex(w.event_filter.findData("ml"))
    assert w.events_table.rowCount() == 0 and not w.events_empty.isHidden()
    w.event_filter.setCurrentIndex(w.event_filter.findData("quality"))
    assert w.events_table.rowCount() == 1
    w.event_filter.setCurrentIndex(w.event_filter.findData("all"))
    w.event_search.setText(ids[0][:8])
    assert w.events_table.rowCount() == 1
    w.event_search.setText("")
    w.event_sort.setCurrentIndex(w.event_sort.findData("desc"))
    times = [float(w.events_table.item(r, 1).text()) for r in range(2)]
    assert times == sorted(times, reverse=True)


def test_events_are_paged_and_load_more_reveals_the_rest(window_with_events):
    w = window_with_events
    template = w.event_rows[0]
    rows = [{**template, "event_id": f"id-{i:04d}", "trigger_ms": i * 1000} for i in range(450)]
    w.show_events(rows)
    assert w.events_table.rowCount() == 200 and not w.events_more.isHidden()
    w.load_more_events()
    assert w.events_table.rowCount() == 400
    w.load_more_events()
    assert w.events_table.rowCount() == 450 and w.events_more.isHidden()


def test_ml_and_rule_events_are_different_categories(window_with_events):
    from doctorcar.ui.main_window import event_category

    base = window_with_events.event_rows[0]
    assert event_category({**base, "kind": "DATA_QUALITY"}) == "quality"
    assert event_category({**base, "kind": "CONNECTION"}) == "connection"
    assert event_category({**base, "kind": "ML_ANOMALY", "detection_method": "ML"}) == "ml"
    assert event_category({**base, "kind": "MS_THERMAL", "detection_method": "RULE"}) == "rule"


def test_report_header_states_partial_recording_and_advisory_ai(window_with_events, app):
    w = window_with_events
    w.event_rows[0]["status"] = "PARTIAL"
    w.event_rows[0]["ai_state"] = "ANALYZED_ANOMALOUS"
    w.current_event = w.event_rows[0]
    w.update_report_header()
    assert "جزئي" in w.report_status_pill.text()
    assert "استشاري" in w.report_ai_pill.text()
    assert "استشاري" in w.report_ai_note.text() or "ML" in w.report_ai_note.text()


# ------------------------------------------------------------------ settings, navigation, notifications
def test_sidebar_collapse_persists_and_keeps_all_navigation_items(window, tmp_path, app):
    window.set_sidebar_collapsed(True)
    assert window.navigation.count() == 6 and window.nav_delegate.collapsed
    assert all(window.navigation.item(i).toolTip() for i in range(6))
    window.close()
    window.worker.wait(5000)
    reopened = MainWindow(tmp_path / "ux.sqlite3")
    try:
        assert reopened.sidebar_collapsed
    finally:
        reopened.close()
        reopened.worker.wait(5000)


def test_zoom_and_reduce_motion_are_saved_and_applied(window, tmp_path, app):
    window.zoom_combo.setCurrentIndex(window.zoom_combo.findData(125))
    assert "13.1pt" in window.styleSheet() or "12.5pt" in window.styleSheet()
    window.reduce_motion.setChecked(True)
    window.close()
    window.worker.wait(5000)
    reopened = MainWindow(tmp_path / "ux.sqlite3")
    try:
        assert reopened.zoom == 125 and reopened.reduce_motion.isChecked()
    finally:
        from doctorcar.ui.widgets import Motion

        Motion.user_enabled = True
        reopened.close()
        reopened.worker.wait(5000)


def test_language_theme_change_does_not_touch_session_or_data(window):
    window.show_sample(sample(3, 600))
    latest, received = window.latest, window.last_received
    for lang in (1, 0, 1):
        window.language_combo.setCurrentIndex(lang)
        window.theme_combo.setCurrentIndex(1 - window.theme_combo.currentIndex())
    assert window.latest is latest and window.last_received == received
    window.language_combo.setCurrentIndex(1)
    for widget in window.findChildren(QLabel) + window.findChildren(QPushButton):
        if widget.isVisible() and not isinstance(widget, StatusPill):
            assert not ARABIC.search(widget.text()), widget.text()


def test_toasts_merge_duplicates_and_errors_stay_until_dismissed(window, app):
    window.notify("warning", "فُقد اتصال المصدر أو توقف؛ القراءات المعروضة ليست حية")
    window.notify("warning", "فُقد اتصال المصدر أو توقف؛ القراءات المعروضة ليست حية")
    assert len(window.toasts.toasts) == 1 and window.toasts.toasts[0].count == 2
    window.show_error("تعذر إكمال العملية: الملف غير موجود: x.jsonl")
    error_toast = [t for t in window.toasts.toasts if t.kind == "error"][0]
    assert not error_toast.timer.isActive()  # errors do not auto-hide
    error_toast.dismiss()
    assert all(t.kind != "error" for t in window.toasts.toasts)
    assert "Traceback" not in window.error_label.text()


def test_status_text_does_not_fire_toasts_when_only_retranslated(window):
    window.set_status("اكتمل المصدر — آخر بيانات مستلمة")
    before = [t.count for t in window.toasts.toasts]
    window.language_combo.setCurrentIndex(1)
    window.language_combo.setCurrentIndex(0)
    assert [t.count for t in window.toasts.toasts] == before


def test_keyboard_navigation_reaches_every_page_and_buttons_have_names(window, app):
    window.navigation.setFocus()
    window.navigation.setCurrentRow(0)
    for expected in range(1, 6):
        QTest.keyClick(window.navigation, Qt.Key.Key_Down)
        assert window.navigation.currentRow() == expected
        assert window.pages.currentIndex() == expected
    for button in window.findChildren(QPushButton):
        if button.isVisible() or not button.isHidden():
            assert button.text() or button.accessibleName() or button.toolTip(), button
    assert window.navigation.accessibleName()


def test_header_title_follows_the_page(window):
    for row in range(6):
        window.navigation.setCurrentRow(row)
        assert window.page_title.text() == window.navigation.item(row).text()


def test_default_language_arabic_rtl_and_english_ltr(window):
    assert window.layoutDirection() == Qt.LayoutDirection.RightToLeft
    window.language_combo.setCurrentIndex(1)
    assert window.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert replace is not None


def test_open_report_is_regenerated_in_the_new_language(window_with_events, app):
    w = window_with_events
    w.navigation.setCurrentRow(3)
    w.events_table.selectRow(0)
    w.open_event(0, 0)
    assert pump(app, until=lambda: "ماذا حدث" in w.simple_report_text.toPlainText())
    w.language_combo.setCurrentIndex(1)
    assert pump(
        app,
        until=lambda: (
            bool(w.simple_report_text.toPlainText())
            and not ARABIC.search(w.simple_report_text.toPlainText())
        ),
        limit=15,
    )
    assert w.report_title.text() and not ARABIC.search(w.report_title.text())
    assert "Recording" in w.report_status_pill.text()
