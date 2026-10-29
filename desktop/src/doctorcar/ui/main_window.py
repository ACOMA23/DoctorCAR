from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QLocale, QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QResizeEvent, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from doctorcar.analysis import status as ai
from doctorcar.core.models import Quality, Sample
from doctorcar.core.sensor_registry import REGISTRY
from doctorcar.monitoring.evidence_rules import RULES
from doctorcar.sources.faults import FAULTS, FaultInstance
from doctorcar.sources.scenarios import SCENARIOS_MS, ScenarioInstance
from doctorcar.sources.simulation import SimulationSource
from doctorcar.ui import theme as design
from doctorcar.ui.localization import translate
from doctorcar.ui.timeseries_plot import TimeSeriesPlot
from doctorcar.ui.widgets import (
    AdaptiveGrid,
    EmptyState,
    EventTimeline,
    MetricTile,
    Motion,
    NavDelegate,
    StatusPill,
    ToastHost,
    button,
    card,
    fade_in,
    label,
    make_icon,
    set_property,
)
from doctorcar.ui.worker import BackendWorker

QUALITY_AR = {
    Quality.AVAILABLE: "متاحة",
    Quality.MISSING: "مفقودة",
    Quality.UNSUPPORTED: "غير مدعومة",
    Quality.INVALID: "غير صالحة",
    Quality.STALE: "قديمة",
}
KIND_AR = {
    "THERMAL_DEMO": "ارتفاع حراري تجريبي",
    "DATA_QUALITY": "جودة بيانات",
    "CONNECTION": "انقطاع اتصال",
}
KIND_AR.update({key: rule.pattern_ar for key, rule in RULES.items()})
STATUS_AR = {"COMPLETE": "مكتمل", "PARTIAL": "جزئي", "RECORDING": "قيد التسجيل"}
NAV_ICONS = ("dashboard", "connection", "sensors", "events", "report", "settings")
NAV_NAMES = (
    "لوحة التحكم",
    "مركز المصادر",
    "قراءات الحساسات",
    "سجل الأحداث",
    "تفاصيل الحدث والتقرير",
    "الإعدادات",
)
SENSOR_GROUPS = (
    ("engine", "المحرك والحمل", ("RPM", "ENGINE_LOAD", "THROTTLE_POS")),
    ("motion", "الحركة", ("SPEED",)),
    ("thermal", "الحرارة", ("COOLANT_TEMP", "INTAKE_TEMP")),
    ("air", "الهواء والوقود", ("INTAKE_PRESSURE", "MAF", "SHORT_FUEL_TRIM", "LONG_FUEL_TRIM")),
    ("electrical", "الكهرباء", ("CONTROL_MODULE_VOLTAGE",)),
    ("diag", "معلومات تشخيصية", ("DTC",)),
)
# Display-only size of a change that is worth a short highlight; not a diagnostic threshold.
HIGHLIGHT_DELTA = {
    "RPM": 150.0,
    "SPEED": 5.0,
    "COOLANT_TEMP": 1.5,
    "ENGINE_LOAD": 8.0,
    "THROTTLE_POS": 5.0,
    "INTAKE_PRESSURE": 5.0,
    "MAF": 3.0,
    "INTAKE_TEMP": 2.0,
    "SHORT_FUEL_TRIM": 3.0,
    "LONG_FUEL_TRIM": 3.0,
    "CONTROL_MODULE_VOLTAGE": 0.4,
}
DASH_SENSORS = ("RPM", "SPEED", "COOLANT_TEMP", "ENGINE_LOAD", "CONTROL_MODULE_VOLTAGE")
SOURCE_HINTS = {
    "simulation": "بيانات محاكاة مولّدة داخل البرنامج؛ لا يُفتح أي منفذ ولا اتصال بمركبة.",
    "replay": "إعادة تشغيل ملف جلسة محفوظ بالسرعة المسجلة؛ اختر ملف JSON Lines.",
    "protocol_file": "ملف يحاكي رسائل جهاز DoctorCAR (JSON Lines v1) للتحقق من البروتوكول.",
    "serial": "جهاز DoctorCAR تجريبي عبر USB Serial. لا يُفتح المنفذ إلا بعد ضغط الفحص أو البدء.",
    "device_simulator": "محاكاة لذاكرة جهاز ترسل أحداثًا تاريخية؛ لا اتصال بعتاد.",
    "network": "اتصال TCP محلي (127.0.0.1 فقط) بمحاكي الجهاز؛ لا شبكة خارجية.",
}
EVENT_FILTERS = (
    ("all", "كل الأحداث"),
    ("rule", "القواعد"),
    ("ml", "ML استشاري"),
    ("quality", "جودة البيانات"),
    ("connection", "اتصال"),
)
EVENTS_PAGE = 200
STALE_AFTER_S = 3.0


def ltr(text: str) -> str:
    """Keep negative numbers, technical IDs and units intact inside RTL paragraphs."""
    return "⁦" + text + "⁩"


def event_category(data: dict[str, Any]) -> str:
    kind = str(data.get("kind", ""))
    if kind == "DATA_QUALITY":
        return "quality"
    if kind == "CONNECTION":
        return "connection"
    if kind == "ML_ANOMALY" or data.get("detection_method") == "ML":
        return "ml"
    return "rule"


class TechnicalDelegate(QStyledItemDelegate):
    def displayText(self, value: Any, locale: QLocale | QLocale.Language) -> str:
        # Change presentation only: the item retains its unmodified database ID.
        return ltr(str(value))


def page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    """A page body. The title is shown by the window header; only the explanatory line lives here."""
    widget = QWidget()
    widget.setObjectName("page")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(4, 4, 4, 8)
    layout.setSpacing(16)
    note = label(subtitle, "muted", wrap=True)
    layout.addWidget(note)
    widget.setProperty("page_title", title)
    return widget, layout


class MainWindow(QMainWindow):
    report_text: QTextEdit

    def __init__(self, database: Path) -> None:
        super().__init__()
        self.preferences = QSettings(
            str(database.resolve().with_suffix(".settings.ini")), QSettings.Format.IniFormat
        )
        self.language = str(self.preferences.value("language", "ar"))
        self.theme = str(self.preferences.value("theme", "light"))
        self.zoom = int(str(self.preferences.value("zoom", 100)))
        Motion.user_enabled = str(self.preferences.value("reduce_motion", "false")) != "true"
        self.event_rows: list[dict[str, Any]] = []
        self.events_shown = EVENTS_PAGE
        self.setWindowTitle("DoctorCAR | المراقبة والتسجيل التجريبي")
        self.setMinimumSize(980, 640)
        self.resize(1240, 820)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFont(design.app_font())
        self.latest: Sample | None = None
        self.last_received = 0.0
        self.backend_ready = False
        self.closing = False
        self.running = False
        self.run_started = 0.0
        self.session_accepted = 0
        self.session_id = ""
        self.device_state = ""
        self.finished_summary: dict[str, Any] | None = None
        self.current_event: dict[str, Any] | None = None
        self._navigate_on_report = True
        self.ai_decision = "UNAVAILABLE"
        self.ai_pill_state: tuple[str, str, str] = ("AI غير متاح", "idle", "")
        self.startup_ai: tuple[bool, str] | None = None
        self.sidebar_collapsed = str(self.preferences.value("sidebar_collapsed", "false")) == "true"
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(18)
        self._build_sidebar(outer)
        content = QVBoxLayout()
        content.setSpacing(10)
        outer.addLayout(content, 1)
        self._build_header(content)
        self.notice = QLabel("بيانات محاكاة واختبار فقط — النتائج ليست تشخيصًا قاطعًا لعطل ميكانيكي")
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        content.addWidget(self.notice)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label.setAccessibleName("error message")
        self.error_label.hide()
        content.addWidget(self.error_label)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        self._dashboard()
        self._sources()
        self._sensors()
        self._events()
        self._report()
        self._settings(database)
        footer = QHBoxLayout()
        self.status_label = QLabel("تهيئة التخزين المحلي…")
        self.status_label.setProperty("role", "muted")
        footer.addWidget(self.status_label, 1)
        content.addLayout(footer)
        self.toasts = ToastHost(root)
        self.toasts.theme = self.theme
        self.navigation.currentRowChanged.connect(self.on_page_changed)
        self.navigation.setCurrentRow(0)
        self.worker = BackendWorker(database)
        self.worker.snapshot.connect(self.show_sample)
        self.worker.events_changed.connect(self.show_events)
        self.worker.report_ready.connect(self.show_report)
        self.worker.simple_report_ready.connect(self.show_simple_report)
        self.worker.ai_changed.connect(self.show_ai)
        self.worker.plot_ready.connect(self.show_plot)
        self.worker.status_changed.connect(self.set_status)
        self.worker.error.connect(self.show_error)
        self.worker.initialized.connect(self.on_ready)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.running_changed.connect(self.set_running)
        self.worker.ports_changed.connect(self.show_ports)
        self.worker.verification_changed.connect(self.show_verification)
        self.worker.device_changed.connect(self.show_device)
        self.worker.simulation_changed.connect(self.show_simulation)
        self.worker.session_stats.connect(self.show_stats)
        for spin in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            spin.setLocale(QLocale.c())  # Latin digits in both languages (technical values)
        self._restore_preferences()
        self._capture_texts()
        self.apply_preferences()
        self._wire_tab_order()
        self.worker.start()
        self.age_timer = QTimer(self)
        self.age_timer.timeout.connect(self.update_age)
        self.age_timer.start(500)

    # ------------------------------------------------------------------ shell
    def _build_sidebar(self, outer: QHBoxLayout) -> None:
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 20, 12, 14)
        side.setSpacing(10)
        brand_row = QHBoxLayout()
        self.brand_mark = QLabel()
        self.brand_mark.setFixedSize(34, 34)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        self.brand = QLabel("DoctorCAR")
        self.brand.setProperty("role", "subtitle")
        self.brand.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.tagline = QLabel("مراقبة • أدلة • فهم")
        self.tagline.setProperty("role", "caption")
        self.tagline.setWordWrap(True)
        brand_box.addWidget(self.brand)
        brand_box.addWidget(self.tagline)
        brand_row.addWidget(self.brand_mark)
        self.brand_text = QWidget()
        self.brand_text.setLayout(brand_box)
        brand_row.addWidget(self.brand_text, 1)
        side.addLayout(brand_row)
        self.navigation = QListWidget()
        self.navigation.setObjectName("nav")
        self.navigation.addItems(list(NAV_NAMES))
        self.navigation.setAccessibleName("main navigation")
        self.navigation.setMouseTracking(True)
        self.navigation.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.nav_delegate = NavDelegate(self.navigation, self.theme)
        self.navigation.setItemDelegate(self.nav_delegate)
        side.addWidget(self.navigation, 1)
        self.sidebar_toggle = button("", "ghost", "طي القائمة / توسيعها")
        self.sidebar_toggle.setAccessibleName("collapse navigation")
        self.sidebar_toggle.clicked.connect(
            lambda: self.set_sidebar_collapsed(not self.sidebar_collapsed)
        )
        side.addWidget(self.sidebar_toggle)
        self.version = QLabel("الإصدار التأسيسي M1\nلا اتصال فعلي بالمركبة")
        self.version.setProperty("role", "caption")
        self.version.setWordWrap(True)
        side.addWidget(self.version)
        outer.addWidget(self.sidebar)

    def _build_header(self, content: QVBoxLayout) -> None:
        header = QWidget()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.breadcrumb = label("DOCTORCAR M1", "caption")
        self.breadcrumb.hide()
        self.page_title = label("", "title", wrap=True)
        self.page_title.setAccessibleName("page title")
        titles.addWidget(self.breadcrumb)
        titles.addWidget(self.page_title)
        row.addLayout(titles, 1)
        self.conn_pill = StatusPill("غير متصل", "idle")
        self.conn_pill.setAccessibleName("connection state")
        self.ai_pill = StatusPill("AI غير متاح", "idle")
        self.ai_pill.setAccessibleName("AI state")
        row.addWidget(self.conn_pill)
        row.addWidget(self.ai_pill)
        content.addWidget(header)

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self.sidebar_collapsed = collapsed
        self.preferences.setValue("sidebar_collapsed", "true" if collapsed else "false")
        self.sidebar.setFixedWidth(76 if collapsed else int(232 * min(self.zoom, 125) / 100))
        self.nav_delegate.collapsed = collapsed
        for widget in (self.brand_text, self.version):
            widget.setVisible(not collapsed)
        self.sidebar_toggle.setText("" if collapsed else self.t("طي القائمة"))
        self.sidebar_toggle.setIcon(
            make_icon("collapse", design.palette(self.theme).sidebar_muted, 18)
        )
        self.navigation.viewport().update()

    def on_page_changed(self, row: int) -> None:
        if row < 0:
            return
        self.pages.setCurrentIndex(row)
        self.page_title.setText(self.t(NAV_NAMES[row]))
        current = self.pages.currentWidget()
        if current is not None:
            fade_in(current)
        if row == 3:
            self.update_events_empty()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.reposition()

    def notify(self, kind: str, text: str, sticky: bool = False) -> None:
        self.toasts.push(kind, self.t(text), sticky)

    # ------------------------------------------------------------------ dashboard
    def _dashboard(self) -> None:
        widget, layout = page("لوحة التحكم", "تابع مصدر البيانات، ثم راجع الأحداث وأدلتها المسجلة.")
        hero, hero_layout = card()
        top = QHBoxLayout()
        self.dash_state_pill = StatusPill("غير متصل", "idle")
        self.dash_headline = label("كل قراءة في سياقها", "subtitle", wrap=True)
        top.addWidget(self.dash_state_pill)
        top.addWidget(self.dash_headline, 1)
        hero_layout.addLayout(top)
        self.dash_hint = label("", "muted", wrap=True)
        hero_layout.addWidget(self.dash_hint)
        actions = AdaptiveGrid(150, 8)
        self.dash_start = button("بدء المراقبة", "primary")
        self.dash_start.clicked.connect(self.start_source)
        self.dash_stop = button("إيقاف المراقبة", "danger")
        self.dash_stop.clicked.connect(lambda: self.worker.submit("stop"))
        self.dash_stop.setEnabled(False)
        go = button("اختيار مصدر البيانات")
        go.clicked.connect(lambda: self.navigation.setCurrentRow(1))
        self.dash_report = button("فتح أحدث تقرير")
        self.dash_report.clicked.connect(self.open_latest_report)
        self.dash_events = button("عرض الأحداث")
        self.dash_events.clicked.connect(lambda: self.navigation.setCurrentRow(3))
        actions.set_items([self.dash_start, self.dash_stop, go, self.dash_report, self.dash_events])
        hero_layout.addWidget(actions)
        layout.addWidget(hero)
        cards = AdaptiveGrid(300, 14)
        conn_card, cl = card(8)
        cl.addWidget(label("الاتصال", "subtitle"))
        self.dash_conn_pill = StatusPill("غير متصل", "idle")
        cl.addWidget(self.dash_conn_pill, 0, Qt.AlignmentFlag.AlignLeft)
        self.dash_source = label("المصدر: —", "", wrap=True)
        self.context = QLabel("لم تبدأ جلسة بعد. اختر المحاكاة من مركز المصادر.")
        self.context.setWordWrap(True)
        self.age = QLabel("لا توجد قراءة")
        self.age.setProperty("role", "muted")
        self.age.setWordWrap(True)
        self.dash_source.hide()
        for w in (self.context, self.age):
            cl.addWidget(w)
        cl.addStretch(1)
        sess_card, sl = card(8)
        sl.addWidget(label("الجلسة", "subtitle"))
        self.dash_duration = label("مدة التشغيل: —", "", wrap=True)
        self.dash_samples = label("العينات المستلمة: 0", "")
        self.dash_events_count = label("الأحداث المسجلة: 0", "")
        self.dash_warnings = label("أحداث القواعد في هذه الجلسة: 0", "")
        for w in (
            self.dash_duration,
            self.dash_samples,
            self.dash_events_count,
            self.dash_warnings,
        ):
            w.setProperty("dynamic", True)
            sl.addWidget(w)
        sl.addStretch(1)
        diag_card, dl = card(8)
        dl.addWidget(label("التشخيص", "subtitle"))
        self.dash_monitor_pill = StatusPill("المراقبة متوقفة", "idle")
        dl.addWidget(self.dash_monitor_pill, 0, Qt.AlignmentFlag.AlignLeft)
        self.dash_last_event = label("آخر حدث: لا يوجد", "", wrap=True)
        self.dash_last_event.setProperty("dynamic", True)
        self.dash_ai_pill = StatusPill("AI غير متاح", "idle")
        self.ai_label = QLabel("AI — Unavailable")
        self.ai_label.setWordWrap(True)
        self.ai_label.setProperty("role", "muted")
        ai_note = label(
            "تحليل ML استشاري؛ لا يفتح حدثًا وحده وليس تشخيصًا ميكانيكيًا.", "caption", wrap=True
        )
        for w in (self.dash_last_event, self.dash_ai_pill, self.ai_label, ai_note):
            dl.addWidget(
                w,
                0,
                Qt.AlignmentFlag.AlignLeft if isinstance(w, StatusPill) else Qt.AlignmentFlag(0),
            )
        dl.addStretch(1)
        cards.set_items([conn_card, sess_card, diag_card])
        self.dash_cards = cards
        layout.addWidget(cards)
        layout.addWidget(label("نظرة على المركبة", "subtitle"))
        self.cards: dict[str, MetricTile] = {}
        tiles = AdaptiveGrid(200, 12)
        items: list[QWidget] = []
        for sensor_id in DASH_SENSORS:
            spec = REGISTRY.get(sensor_id)
            tile = MetricTile(sensor_id, spec.arabic_name, spec.unit, spark=False)
            self.cards[sensor_id] = tile
            items.append(tile)
        tiles.set_items(items)
        self.dash_tiles = tiles
        layout.addWidget(tiles)
        sim_card, sim_layout = card(8)
        sim_layout.addWidget(label("نتائج المحاكاة", "subtitle"))
        self.simulation_summary = QTextEdit()
        self.simulation_summary.setReadOnly(True)
        self.simulation_summary.setMaximumHeight(165)
        self.simulation_summary.setPlaceholderText("جدول الحقن ونتائج الكشف — تقييم اختباري فقط")
        sim_layout.addWidget(self.simulation_summary)
        layout.addWidget(sim_card)
        layout.addStretch(1)
        self.add_page(widget)

    def add_page(self, widget: QWidget) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        self.pages.addWidget(scroll)

    # ------------------------------------------------------------------ connection / simulation
    def _sources(self) -> None:
        widget, layout = page(
            "مركز المصادر", "جلسة واحدة تغذي جميع الصفحات. لا يُفتح أي منفذ تلقائيًا."
        )
        state_card, state_layout = card(8)
        row = QHBoxLayout()
        self.source_state_pill = StatusPill("غير متصل", "idle")
        row.addWidget(label("حالة الاتصال", "subtitle"))
        row.addWidget(self.source_state_pill)
        row.addStretch(1)
        state_layout.addLayout(row)
        self.connection_details = QLabel("DISCONNECTED")
        self.connection_details.setWordWrap(True)
        self.connection_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        state_layout.addWidget(self.connection_details)
        layout.addWidget(state_card)
        form_card, form_card_layout = card(10)
        form_card_layout.addWidget(label("1) اختر مصدر البيانات ثم اضبط خياراته", "subtitle"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.ai_enabled = QCheckBox("تفعيل مراقبة AI التجريبية")
        form_card_layout.addWidget(self.ai_enabled)
        self.source_combo = QComboBox()
        self.source_combo.addItem("محاكاة — SIMULATION", "simulation")
        self.source_combo.addItem("إعادة تشغيل ملف — REPLAY", "replay")
        self.source_combo.addItem("محاكي الجهاز / ملف البروتوكول", "protocol_file")
        self.source_combo.addItem("جهاز DoctorCAR تجريبي — USB Serial", "serial")
        self.source_combo.addItem(
            "ذاكرة جهاز محاكاة — SIMULATED DEVICE HISTORY", "device_simulator"
        )
        self.source_combo.addItem("جهاز DoctorCAR عبر الشبكة — تجريبي", "network")
        self.source_hint = label("", "caption", wrap=True)
        self.host_input = QLineEdit("127.0.0.1")
        self.network_port = QSpinBox()
        self.network_port.setRange(1, 65535)
        self.network_port.setValue(8765)
        self.mode_combo = QComboBox()
        self.family_combo = QComboBox()
        self.family_combo.addItem("محاكاة الإشارات السابقة", "legacy")
        self.family_combo.addItem("سيناريوهات مترابطة متعددة القياسات", "multisensor")
        self.multisensor_list = QListWidget()
        self.multisensor_list.setObjectName("faultList")
        self.multisensor_list.setMinimumHeight(160)
        self.multisensor_list.setMaximumHeight(190)
        for definition in SCENARIOS_MS.values():
            item = QListWidgetItem(definition.scenario_id + " — " + definition.arabic_name)
            item.setData(Qt.ItemDataRole.UserRole, definition.scenario_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip(definition.relationships + "\n" + definition.operating_conditions)
            self.multisensor_list.addItem(item)
        self.scenario_info = label("", "caption", wrap=True)
        self.multisensor_list.currentRowChanged.connect(self.show_scenario_info)
        self.variant_combo = QComboBox()
        for title, value in (
            ("فقد متقطع", "dropout"),
            ("قيمة غير منطقية", "implausible"),
            ("ثبات مشتبه", "flatline"),
        ):
            self.variant_combo.addItem(title, value)
        for text, value in (
            ("رحلة طبيعية", "NORMAL"),
            ("حقن أعطال محددة", "FAULT_INJECTION"),
            ("أعطال عشوائية كل 30 ثانية", "RANDOM_FAULTS"),
            ("سيناريو M1 السابق", "LEGACY"),
        ):
            self.mode_combo.addItem(text, value)
        self.scenario_combo = QComboBox()
        for title, value in (
            ("رحلة طبيعية", "normal"),
            ("ارتفاع حراري تجريبي", "thermal"),
            ("قراءة غير منطقية", "invalid"),
            ("انقطاع قراءة", "dropout"),
        ):
            self.scenario_combo.addItem(title, value)
        self.speed_combo = QComboBox()
        for speed in (1, 10, 30):
            self.speed_combo.addItem(f"{speed}×", speed)
        self.path_input = QLineEdit()
        self.path_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.path_input.setPlaceholderText("ملف JSON Lines من جلسة واحدة")
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        port_input = self.port_combo.lineEdit()
        assert port_input is not None
        self.port_input = port_input
        self.port_input.setPlaceholderText("منفذ الجهاز التجريبي مثل COM3 — لا محول سيارة")
        self.refresh_ports = button("تحديث المنافذ")
        self.refresh_ports.clicked.connect(lambda: self.worker.submit("ports"))
        self.fault_list = QListWidget()
        self.fault_list.setObjectName("faultList")
        self.fault_list.setMaximumHeight(135)
        for fault in FAULTS.values():
            item = QListWidgetItem(fault.arabic_name)
            item.setData(Qt.ItemDataRole.UserRole, fault.fault_id)
            item.setToolTip(
                f"{fault.description}\n{fault.expected_evidence}\n"
                f"M1: {', '.join(fault.detected_by) or 'DISPLAY ONLY'}"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.fault_list.addItem(item)
        self.seed_input = QSpinBox()
        self.seed_input.setRange(0, 2_000_000_000)
        self.seed_input.setValue(int(str(self.preferences.value("seed", 42))))
        self.fault_start = QSpinBox()
        self.fault_start.setRange(0, 150)
        self.fault_start.setValue(60)
        self.fault_duration = QSpinBox()
        self.fault_duration.setRange(1, 60)
        self.fault_duration.setValue(5)
        self.severity_input = QDoubleSpinBox()
        self.severity_input.setRange(0.1, 1.0)
        self.severity_input.setSingleStep(0.1)
        self.severity_input.setValue(1.0)
        self.severity_input.setToolTip("0.1 = خفيف جدًا، 1.0 = أقصى شدة")
        self.max_faults_input = QSpinBox()
        self.max_faults_input.setRange(1, 3)
        self.max_faults_input.setValue(3)
        self.normal_probability = QDoubleSpinBox()
        self.normal_probability.setRange(0, 1)
        self.normal_probability.setSingleStep(0.05)
        self.normal_probability.setValue(0.25)
        browse = button("اختيار ملف البيانات")
        browse.clicked.connect(self.choose_replay)
        form.addRow("المصدر", self.source_combo)
        form.addRow("", self.source_hint)
        form.addRow("عنوان الجهاز المحلي", self.host_input)
        form.addRow("منفذ الشبكة", self.network_port)
        form.addRow("عائلة المحاكاة", self.family_combo)
        form.addRow("نوع المحاكاة", self.mode_combo)
        form.addRow("سيناريو المحاكاة", self.scenario_combo)
        form.addRow("الأعطال المختارة", self.fault_list)
        form.addRow("السيناريوهات المترابطة", self.multisensor_list)
        form.addRow("", self.scenario_info)
        form.addRow("نمط إشارة S07", self.variant_combo)
        form.addRow("بداية الحقن (ثانية)", self.fault_start)
        form.addRow("مدة الحقن (ثانية)", self.fault_duration)
        form.addRow("شدة نمط الإشارة", self.severity_input)
        form.addRow("Seed", self.seed_input)
        form.addRow("أقصى أعطال في الدورة", self.max_faults_input)
        form.addRow("احتمال دورة طبيعية", self.normal_probability)
        form.addRow("سرعة العرض", self.speed_combo)
        form.addRow("ملف الإعادة", self.path_input)
        form.addRow("منفذ الجهاز التجريبي", self.port_combo)
        form.addRow("", self.refresh_ports)
        form.addRow("", browse)
        self.source_form = form
        self.browse_button = browse
        form_card_layout.addLayout(form)
        layout.addWidget(form_card, 1)
        run_card, run_layout = card(10)
        run_layout.addWidget(label("2) التحقق والتشغيل", "subtitle"))
        self.verify_button = button("فحص المصدر / الاتصال")
        self.verify_button.clicked.connect(self.verify_source)
        buttons = AdaptiveGrid(170, 8)
        self.start_button = button("بدء الجلسة", "primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_source)
        stop = button("إيقاف وحفظ المتاح", "danger")
        stop.setEnabled(False)
        self.stop_button = stop
        stop.clicked.connect(lambda: self.worker.submit("stop"))
        export = button("تصدير الجلسة لـ Replay")
        export.clicked.connect(self.export_replay)
        buttons.set_items([self.verify_button, self.start_button, stop, export])
        run_layout.addWidget(buttons)
        self.run_time_label = label("", "muted", wrap=True)
        self.run_time_label.setProperty("dynamic", True)
        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 1000)
        self.run_progress.setTextVisible(False)
        self.run_progress.hide()
        run_layout.addWidget(self.run_time_label)
        run_layout.addWidget(self.run_progress)
        note = label(
            "تسريع العرض يحافظ على زمن العينات ونافذة 30 ثانية.\n"
            "الاتصال الحقيقي بـ OBD وCAN وMicroSD غير منفذ في M1.",
            "caption",
            wrap=True,
        )
        run_layout.addWidget(note)
        layout.addWidget(run_card)
        self.summary_card, summary_layout = card(8)
        summary_layout.addWidget(label("ملخص الجلسة المنتهية", "subtitle"))
        self.summary_text = label("", "", wrap=True)
        self.summary_text.setProperty("dynamic", True)
        summary_layout.addWidget(self.summary_text)
        self.summary_events = button("عرض الأحداث والتقارير")
        self.summary_events.clicked.connect(lambda: self.navigation.setCurrentRow(3))
        summary_layout.addWidget(self.summary_events, 0, Qt.AlignmentFlag.AlignLeft)
        self.summary_card.hide()
        layout.addWidget(self.summary_card)
        layout.addStretch(1)
        self.add_page(widget)
        self.source_combo.currentIndexChanged.connect(self.update_source_fields)
        self.mode_combo.currentIndexChanged.connect(self.update_source_fields)
        self.family_combo.currentIndexChanged.connect(self.family_changed)
        self.multisensor_list.itemChanged.connect(self.update_source_fields)
        self.scenario_combo.currentIndexChanged.connect(self.legacy_selected)
        self.update_source_fields()

    def show_scenario_info(self, row: int) -> None:
        definitions = list(SCENARIOS_MS.values())
        if 0 <= row < len(definitions):
            d = definitions[row]
            en = self.language == "en"
            self.scenario_info.setText(
                f"{d.scenario_id}: {d.english_name if en else d.arabic_name}\n"
                f"{d.relationships}\n{d.operating_conditions}"
            )
        else:
            self.scenario_info.setText("")

    # ------------------------------------------------------------------ sensors
    def _sensors(self) -> None:
        widget, layout = page(
            "قراءات الحساسات", "السجل المركزي يحدد الأسماء والوحدات؛ DTC معلومات تشخيصية."
        )
        bar = QHBoxLayout()
        self.sensor_search = QLineEdit()
        self.sensor_search.setPlaceholderText("بحث عن حساس")
        self.sensor_search.setClearButtonEnabled(True)
        self.sensor_search.setMinimumWidth(90)
        self.sensor_search.setAccessibleName("search sensors")
        self.sensor_filter = QComboBox()
        self.sensor_filter.setMinimumContentsLength(11)
        self.sensor_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.sensor_filter.setAccessibleName("sensor group filter")
        self.sensor_filter.addItem("كل الحساسات", "all")
        for key, title, _ in SENSOR_GROUPS:
            self.sensor_filter.addItem(title, key)
        self.sensor_filter.addItem("قراءات غير متاحة", "problem")
        self.view_cards = button("بطاقات", "primary")
        self.view_table = button("جدول")
        self.view_cards.setCheckable(True)
        self.view_table.setCheckable(True)
        self.view_cards.setChecked(True)
        bar.addWidget(self.sensor_search, 1)
        bar.addWidget(self.sensor_filter)
        bar.addWidget(self.view_cards)
        bar.addWidget(self.view_table)
        layout.addLayout(bar)
        self.sensor_empty = EmptyState(
            "sensors",
            "لم تبدأ المراقبة بعد",
            "اختر مصدر بيانات للبدء؛ ستظهر القراءات هنا فور وصول أول عينة.",
            "اختيار مصدر البيانات",
        )
        assert self.sensor_empty.action is not None
        self.sensor_empty.action.clicked.connect(lambda: self.navigation.setCurrentRow(1))
        layout.addWidget(self.sensor_empty, 1)
        self.sensor_views = QStackedWidget()
        self.sensor_tiles: dict[str, MetricTile] = {}
        self.sensor_grid = AdaptiveGrid(220, 12)
        tile_items: list[QWidget] = []
        for spec in REGISTRY.all():
            tile = MetricTile(
                spec.sensor_id, spec.arabic_name, spec.unit, spark=spec.kind != "diagnostic"
            )
            tile.setProperty(
                "group", next((k for k, _, ids in SENSOR_GROUPS if spec.sensor_id in ids), "")
            )
            self.sensor_tiles[spec.sensor_id] = tile
            tile_items.append(tile)
        self.sensor_grid.set_items(tile_items)
        self.sensor_views.addWidget(self.sensor_grid)
        self.sensor_table = QTableWidget(len(REGISTRY.all()), 5)
        self.sensor_table.setHorizontalHeaderLabels(
            ["القراءة", "المعرف", "القيمة", "الوحدة", "الحالة"]
        )
        self.sensor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sensor_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.sensor_table.verticalHeader().hide()
        self.sensor_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sensor_table.setAlternatingRowColors(False)
        for row, spec in enumerate(REGISTRY.all()):
            for col, text in enumerate(
                (spec.arabic_name, ltr(spec.sensor_id), "—", ltr(spec.unit), "لم تصل بيانات")
            ):
                self.sensor_table.setItem(row, col, QTableWidgetItem(text))
        self.sensor_views.addWidget(self.sensor_table)
        layout.addWidget(self.sensor_views, 1)
        self.sensor_empty_results = EmptyState(
            "search", "لا نتائج مطابقة", "غيّر نص البحث أو المجموعة المختارة."
        )
        self.sensor_empty_results.hide()
        layout.addWidget(self.sensor_empty_results)
        self.sensor_views.hide()
        self.view_cards.clicked.connect(lambda: self.set_sensor_view(0))
        self.view_table.clicked.connect(lambda: self.set_sensor_view(1))
        self.sensor_search.textChanged.connect(self.apply_sensor_filter)
        self.sensor_filter.currentIndexChanged.connect(self.apply_sensor_filter)
        self.add_page(widget)

    def set_sensor_view(self, index: int) -> None:
        self.sensor_views.setCurrentIndex(index)
        self.view_cards.setChecked(index == 0)
        self.view_table.setChecked(index == 1)
        set_property(self.view_cards, "variant", "primary" if index == 0 else "")
        set_property(self.view_table, "variant", "primary" if index == 1 else "")

    def apply_sensor_filter(self) -> None:
        text = self.sensor_search.text().strip().lower()
        group = self.sensor_filter.currentData()
        shown = 0
        for row, spec in enumerate(REGISTRY.all()):
            tile = self.sensor_tiles[spec.sensor_id]
            name = (self.t(spec.arabic_name) + " " + spec.sensor_id).lower()
            ok = (not text or text in name) and (
                group in ("all", None, "problem") or tile.property("group") == group
            )
            if group == "problem":
                ok = ok and tile.quality_key not in ("AVAILABLE",) and self.latest is not None
            tile.setVisible(ok)
            self.sensor_table.setRowHidden(row, not ok)
            shown += ok
        self.sensor_grid.reflow()
        self.sensor_empty_results.setVisible(shown == 0 and self.latest is not None)

    # ------------------------------------------------------------------ events
    def _events(self) -> None:
        widget, layout = page(
            "سجل الأحداث", "الأحداث محفوظة محليًا وتبقى متاحة بعد إعادة تشغيل التطبيق."
        )
        bar = AdaptiveGrid(170, 8)
        self.event_search = QLineEdit()
        self.event_search.setPlaceholderText("بحث في الأحداث")
        self.event_search.setClearButtonEnabled(True)
        self.event_search.setMinimumWidth(90)
        self.event_search.setAccessibleName("search events")
        self.event_filter = QComboBox()
        self.event_filter.setMinimumContentsLength(13)
        self.event_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.event_filter.setAccessibleName("event type filter")
        for key, title in EVENT_FILTERS:
            self.event_filter.addItem(title, key)
        self.event_sort = QComboBox()
        self.event_sort.setMinimumContentsLength(7)
        self.event_sort.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.event_sort.setAccessibleName("event order")
        self.event_sort.addItem("الأقدم أولًا", "asc")
        self.event_sort.addItem("الأحدث أولًا", "desc")
        refresh = button("تحديث السجل")
        refresh.clicked.connect(lambda: self.worker.submit("refresh"))
        bar.set_items([self.event_search, self.event_filter, self.event_sort, refresh])
        layout.addWidget(bar)
        self.events_table = QTableWidget(0, 9)
        self.events_table.setHorizontalHeaderLabels(
            [
                "الحدث",
                "لحظة الكشف (ثانية)",
                "التسجيل",
                "المعرف",
                "أصل الحدث",
                "النظام المحتمل",
                "أدلة داعمة",
                "الفحوص المقترحة",
                "طريقة الكشف",
            ]
        )
        header = self.events_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((210, 150, 100, 150, 90, 190, 100, 280, 130)):
            self.events_table.setColumnWidth(column, width)
        self.events_table.verticalHeader().hide()
        self.events_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.events_table.setItemDelegateForColumn(3, TechnicalDelegate(self.events_table))
        self.events_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.events_table.setWordWrap(True)
        self.events_table.cellDoubleClicked.connect(self.open_event)
        self.events_table.cellActivated.connect(self.open_event)  # Enter key
        self.events_table.setAccessibleName("events table")
        self.events_empty = EmptyState(
            "inbox",
            "لا توجد أحداث مسجلة بعد",
            "ستظهر الأحداث المكتشفة هنا مع تسجيل 30 ثانية قبل الكشف وبعده.",
        )
        layout.addWidget(self.events_empty, 1)
        layout.addWidget(self.events_table, 1)
        foot = QHBoxLayout()
        self.events_count = label("", "caption", wrap=True)
        self.events_count.setProperty("dynamic", True)
        self.events_more = button("تحميل المزيد")
        self.events_more.clicked.connect(self.load_more_events)
        self.events_more.hide()
        open_button = button("عرض تقرير الحدث المحدد", "primary")
        open_button.clicked.connect(lambda: self.open_event(self.events_table.currentRow(), 0))
        foot.addWidget(self.events_count, 1)
        foot.addWidget(self.events_more)
        foot.addWidget(open_button)
        layout.addLayout(foot)
        self.event_search.textChanged.connect(lambda _t: self.show_events(self.event_rows))
        self.event_filter.currentIndexChanged.connect(lambda _i: self.show_events(self.event_rows))
        self.event_sort.currentIndexChanged.connect(lambda _i: self.show_events(self.event_rows))
        self.add_page(widget)

    def load_more_events(self) -> None:
        self.events_shown += EVENTS_PAGE
        self.show_events(self.event_rows)

    def update_events_empty(self) -> None:
        empty = not self.event_rows
        filtered_out = bool(self.event_rows) and self.events_table.rowCount() == 0
        self.events_empty.setVisible(empty or filtered_out)
        if filtered_out:
            self.events_empty.set_texts(
                self.t("لا نتائج مطابقة"), self.t("غيّر نص البحث أو نوع الحدث.")
            )
        elif empty:
            self.events_empty.set_texts(
                self.t("لا توجد أحداث مسجلة بعد"),
                self.t("ستظهر الأحداث المكتشفة هنا مع تسجيل 30 ثانية قبل الكشف وبعده."),
            )
        self.events_table.setVisible(not (empty or filtered_out))

    # ------------------------------------------------------------------ report
    def _report(self) -> None:
        widget, layout = page(
            "تفاصيل الحدث والتقرير", "الملاحظة والأدلة والبدائل والبيانات الناقصة والفحص المقترح."
        )
        head, head_layout = card(8)
        row = QHBoxLayout()
        self.report_title = label("اختر حدثًا من السجل", "subtitle", wrap=True)
        self.report_title.setProperty("dynamic", True)
        self.report_status_pill = StatusPill("—", "idle")
        self.report_ai_pill = StatusPill("AI —", "idle")
        row.addWidget(self.report_title, 1)
        row.addWidget(self.report_status_pill)
        row.addWidget(self.report_ai_pill)
        head_layout.addLayout(row)
        self.report_meta = label("", "muted", wrap=True)
        self.report_meta.setProperty("dynamic", True)
        head_layout.addWidget(self.report_meta)
        self.timeline = EventTimeline()
        head_layout.addWidget(self.timeline)
        self.report_ai_note = label("", "caption", wrap=True)
        self.report_ai_note.setProperty("dynamic", True)
        head_layout.addWidget(self.report_ai_note)
        layout.addWidget(head)
        self.report_empty = EmptyState(
            "report", "لا يوجد تقرير معروض", "افتح حدثًا من سجل الأحداث لعرض تقريره.", "عرض الأحداث"
        )
        assert self.report_empty.action is not None
        self.report_empty.action.clicked.connect(lambda: self.navigation.setCurrentRow(3))
        layout.addWidget(self.report_empty)
        self.simple_report_text = QTextEdit()
        self.simple_report_text.setReadOnly(True)
        self.simple_report_text.setMinimumHeight(240)
        self.simple_report_text.setAccessibleName("simple report")
        layout.addWidget(self.simple_report_text)
        tools = QHBoxLayout()
        self.copy_simple = button("نسخ التقرير المبسط")
        self.copy_simple.clicked.connect(lambda: self.copy_text(self.simple_report_text))
        self.technical_button = button("عرض التفاصيل الفنية")
        self.technical_button.setCheckable(True)
        self.copy_technical = button("نسخ التقرير الفني")
        self.copy_technical.clicked.connect(lambda: self.copy_text(self.report_text))
        self.copy_technical.hide()
        tools.addWidget(self.copy_simple)
        tools.addWidget(self.technical_button)
        tools.addWidget(self.copy_technical)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setMinimumHeight(260)
        self.report_text.setAccessibleName("technical report")
        self.report_text.setPlainText("اختر حدثًا من السجل لعرض تقريره.")
        layout.addWidget(self.report_text)
        self.report_text.hide()
        self.technical_button.toggled.connect(self.report_text.setVisible)
        self.technical_button.toggled.connect(self.copy_technical.setVisible)
        self.time_plot = TimeSeriesPlot()
        layout.addWidget(self.time_plot)
        self.time_plot.hide()
        self.technical_button.toggled.connect(self.time_plot.setVisible)
        layout.addStretch(1)
        self.add_page(widget)

    def copy_text(self, editor: QTextEdit) -> None:
        text = editor.toPlainText()
        if not text.strip():
            self.notify("warning", "لا يوجد نص لنسخه")
            return
        QGuiApplication.clipboard().setText(text)
        self.notify("success", "تم نسخ النص إلى الحافظة")

    def show_simple_report(self, text: str) -> None:
        self.simple_report_text.setPlainText(text)
        cursor = QTextCursor(self.simple_report_text.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        block.setLineHeight(135, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block)
        self.report_empty.setVisible(not text.strip())
        self.simple_report_text.setVisible(bool(text.strip()))
        self.report_status_pill.set_state(self.t("جاهز"), "ok")

    def show_plot(self, data: dict[str, Any]) -> None:
        self.time_plot.set_series(data, self.language)
        times = [p[0] for series in data.values() for p in series]
        if times and self.current_event is not None:
            self.timeline.set_window(
                float(self.current_event["trigger_ms"]),
                float(min(times)),
                float(max(times)),
                str(self.current_event.get("status", "")),
            )
            self.update_report_header()

    # ------------------------------------------------------------------ settings
    def _settings(self, database: Path) -> None:
        widget, layout = page("الإعدادات", "إعدادات محدودة؛ لا وظائف اتصال مخفية أو غير منفذة.")
        lang_card, lang_layout = card(10)
        lang_layout.addWidget(label("اللغة والمظهر", "subtitle"))
        settings_form = QFormLayout()
        self.language_combo = QComboBox()
        self.language_combo.addItem("العربية — AR", "ar")
        self.language_combo.addItem("English — EN", "en")
        self.language_combo.setCurrentIndex(1 if self.language == "en" else 0)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("فاتح — Light", "light")
        self.theme_combo.addItem("داكن — Dark", "dark")
        self.theme_combo.setCurrentIndex(1 if self.theme == "dark" else 0)
        settings_form.addRow("اللغة", self.language_combo)
        settings_form.addRow("المظهر", self.theme_combo)
        lang_layout.addLayout(settings_form)
        layout.addWidget(lang_card)
        display_card, display_layout = card(10)
        display_layout.addWidget(label("العرض", "subtitle"))
        display_form = QFormLayout()
        self.zoom_combo = QComboBox()
        for percent in (90, 100, 110, 125, 150):
            self.zoom_combo.addItem(f"{percent}%", percent)
        self.zoom_combo.setCurrentIndex(max(0, self.zoom_combo.findData(self.zoom)))
        self.reduce_motion = QCheckBox("تقليل الحركة")
        self.reduce_motion.setChecked(not Motion.user_enabled)
        display_form.addRow("حجم العرض", self.zoom_combo)
        display_layout.addLayout(display_form)
        display_layout.addWidget(self.reduce_motion)
        display_layout.addWidget(
            label("الحركة تتوقف تلقائيًا أيضًا إذا عطّل Windows تأثيرات الحركة.", "caption", wrap=True)
        )
        layout.addWidget(display_card)
        conn_card, conn_layout = card(8)
        conn_layout.addWidget(label("تفضيلات الاتصال", "subtitle"))
        self.remember_source = QCheckBox("تذكر آخر مصدر وتفعيل AI عند التشغيل")
        self.remember_source.setChecked(
            str(self.preferences.value("remember_source", "true")) == "true"
        )
        conn_layout.addWidget(self.remember_source)
        conn_layout.addWidget(
            label(
                "لا يُفتح أي منفذ أو اتصال تلقائيًا؛ التشغيل يبدأ فقط بطلب المستخدم.",
                "caption",
                wrap=True,
            )
        )
        layout.addWidget(conn_card)
        about, about_layout = card(8)
        about_layout.addWidget(label("عن DoctorCAR", "subtitle"))
        note = QLabel(
            "نموذج أولي لمراقبة المركبة وتسجيل الأحداث العابرة؛ البيانات محاكاة أو اختبار.\n"
            "نافذة الحدث: 30 ثانية قبل و30 ثانية بعد، حسب البيانات المتاحة\n"
            "دقة المحاكاة: قراءة كل 200 ms من زمن السيناريو\n"
            "المصدر الافتراضي: محاكاة؛ يبدأ فقط بطلب المستخدم"
        )
        note.setWordWrap(True)
        self.about_ai = label("", "muted", wrap=True)
        self.about_ai.setProperty("dynamic", True)
        about_layout.addWidget(note)
        about_layout.addWidget(self.about_ai)
        db = QLineEdit(str(database.resolve()))
        db.setReadOnly(True)
        db.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        db.setAccessibleName("database path")
        about_layout.addWidget(db)
        about_layout.addWidget(
            label("يمكن تغيير ملف التخزين عند التشغيل باستخدام --database", "caption", wrap=True)
        )
        layout.addWidget(about)
        layout.addStretch()
        self.language_combo.currentIndexChanged.connect(self.apply_preferences)
        self.theme_combo.currentIndexChanged.connect(self.apply_preferences)
        self.zoom_combo.currentIndexChanged.connect(self.apply_preferences)
        self.reduce_motion.toggled.connect(self.apply_preferences)
        self.remember_source.toggled.connect(self.apply_preferences)
        self.add_page(widget)

    def _restore_preferences(self) -> None:
        if str(self.preferences.value("remember_source", "true")) == "true":
            self.ai_enabled.setChecked(str(self.preferences.value("ai_enabled", "false")) == "true")
            index = self.source_combo.findData(
                str(self.preferences.value("last_source", "simulation"))
            )
            if index >= 0:
                self.source_combo.setCurrentIndex(index)
        self.set_sidebar_collapsed(self.sidebar_collapsed)

    def name_form_fields(self) -> None:
        """Accessible names for form fields come from their visible row labels (current language)."""
        for form in (self.source_form,):
            for row in range(form.rowCount()):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if label_item is None or field_item is None:
                    continue
                label_widget, field_widget = label_item.widget(), field_item.widget()
                if (
                    isinstance(label_widget, QLabel)
                    and field_widget is not None
                    and label_widget.text()
                ):
                    field_widget.setAccessibleName(label_widget.text())
        for control, name in (
            (self.language_combo, "اللغة"),
            (self.theme_combo, "المظهر"),
            (self.zoom_combo, "حجم العرض"),
            (self.ai_enabled, "تفعيل مراقبة AI التجريبية"),
            (self.reduce_motion, "تقليل الحركة"),
            (self.speed_combo, "سرعة العرض"),
            (self.path_input, "ملف الإعادة"),
            (self.host_input, "عنوان الجهاز المحلي"),
            (self.network_port, "منفذ الشبكة"),
        ):
            control.setAccessibleName(self.t(name))

    def _wire_tab_order(self) -> None:
        order = [self.navigation, self.sidebar_toggle, self.dash_start, self.dash_stop]
        for first, second in zip(order, order[1:], strict=False):
            QWidget.setTabOrder(first, second)

    # ------------------------------------------------------------------ backend ready / start
    def on_ready(self) -> None:
        self.backend_ready = True
        self.start_button.setEnabled(not self.running)
        self.dash_start.setEnabled(not self.running)
        self.set_status("جاهز — لا يوجد اتصال بالمركبة")
        self.refresh_dashboard()

    def attach_startup_result(self, ai_ok: bool, info: str) -> None:
        """Called by the launcher once the model preload finished (or failed)."""
        self.startup_ai = (ai_ok, info)
        if ai_ok:
            self.about_ai.setText(self.t("نموذج AI المحمّل: ") + info)
            self.ai_pill_state = ("AI جاهز — استشاري", "info", info)
            self.render_ai_pills()
        else:
            self.about_ai.setText(self.t("نموذج AI غير متاح؛ تعمل القواعد والتسجيل بدونه."))
            self.ai_pill_state = ("AI غير متاح", "warn", info)
            self.render_ai_pills()
            self.notify("warning", "تعذر تحميل نموذج AI؛ تعمل القواعد والتسجيل دونه")

    def start_source(self) -> None:
        self.error_label.hide()
        try:
            self.worker.submit("start", **self.source_arguments())
        except ValueError as exc:
            self.show_error(str(exc))

    def choose_replay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("ملف إعادة التشغيل"),
            "",
            "JSON Lines (*.jsonl)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.path_input.setText(path)
            if self.source_combo.currentData() not in ("replay", "protocol_file"):
                self.source_combo.setCurrentIndex(1)

    def export_replay(self) -> None:
        if self.latest is None:
            self.show_error("لا توجد جلسة لتصديرها")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.t("تصدير الجلسة"),
            "trip.jsonl",
            "JSON Lines (*.jsonl)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.worker.submit("export", session_id=self.latest.session_id, path=path)

    # ------------------------------------------------------------------ live data
    def show_sample(self, sample: Sample) -> None:
        self.latest, self.last_received = sample, time.monotonic()
        self.session_id = sample.session_id
        self.context.setText(
            self.t(
                f"المصدر: {sample.source.value}  •  الحالة: {sample.phase}\n"
                f"زمن الجلسة: {sample.timestamp_ms / 1000:.1f} ثانية  •  "
                f"التسلسل: {sample.sequence_number}"
            )
        )
        self.sensor_empty.hide()
        self.sensor_views.show()
        for row, spec in enumerate(REGISTRY.all()):
            tile = self.sensor_tiles[spec.sensor_id]
            numeric: float | None = None
            quality_key = "NONE"
            if spec.kind == "diagnostic":
                value = (
                    ", ".join(sample.dtcs) or self.t("لا رمز مرصود")
                    if sample.dtc_quality == Quality.AVAILABLE
                    else "—"
                )
                status = "معلومات تشخيصية — " + QUALITY_AR[sample.dtc_quality]
                quality_key = sample.dtc_quality.name
                quality_text = QUALITY_AR[sample.dtc_quality]
            else:
                r = sample.readings.get(spec.sensor_id)
                value = f"{r.value:.1f}" if r and r.value is not None else "—"
                status = QUALITY_AR[r.quality] if r else "مفقودة"
                quality_key = r.quality.name if r else "MISSING"
                quality_text = status
                numeric = r.value if r and r.value is not None else None
            value_item, status_item = self.sensor_table.item(row, 2), self.sensor_table.item(row, 4)
            assert value_item is not None and status_item is not None
            value_item.setText(ltr(value))
            status_item.setText(self.t(status))
            name_item = self.sensor_table.item(row, 0)
            assert name_item is not None
            name_item.setText(self.t(spec.arabic_name))
            shown = "—" if value == "—" else value
            tile.quality_key = quality_key
            tile.set_reading(
                ltr(shown),
                quality_key,
                self.t(quality_text),
                self.t("الآن"),
                numeric,
                HIGHLIGHT_DELTA.get(spec.sensor_id, 5.0),
                False,
                self.theme,
                True,
            )
            tile.name_label.setText(self.t(spec.arabic_name))
            dash = self.cards.get(spec.sensor_id)
            if dash is not None:
                dash.quality_key = quality_key
                dash.set_reading(
                    ltr(shown),
                    quality_key,
                    self.t(quality_text),
                    self.t("الآن"),
                    numeric,
                    HIGHLIGHT_DELTA.get(spec.sensor_id, 5.0),
                    False,
                    self.theme,
                    True,
                )
                dash.name_label.setText(self.t(spec.arabic_name))
                dash.setVisible(quality_key != "UNSUPPORTED")
        self.dash_tiles.reflow()
        self.refresh_dashboard()

    def update_age(self) -> None:
        if self.latest:
            seconds = time.monotonic() - self.last_received
            stale = seconds > STALE_AFTER_S
            state = "قديمة — ليست قراءة حية" if stale else "آخر بيانات مستلمة"
            self.age.setText(
                self.fmt(
                    f"{state} • منذ {seconds:.1f} ثانية • {self.latest.source.value}",
                    f"{self.t(state)} • {seconds:.1f} s ago • {self.latest.source.value}",
                )
            )
            if stale:
                for tile in [*self.sensor_tiles.values(), *self.cards.values()]:
                    if tile.quality_key == "AVAILABLE" or tile.property("state") != "stale":
                        tile.quality.set_state(self.t("قديمة — ليست حية"), "warn")
                        tile.age_label.setText(
                            self.fmt(f"منذ {seconds:.0f} ث", f"{seconds:.0f} s ago")
                        )
                        set_property(tile, "state", "stale")
                        tile.last_value = None
            elif self.running:
                for tile in [*self.sensor_tiles.values(), *self.cards.values()]:
                    tile.age_label.setText(self.t("الآن") if seconds < 1.5 else f"{seconds:.0f}s")
            if self.running and self.run_started:
                self.update_run_panel()
            self.refresh_dashboard()
        elif self.running:
            self.update_run_panel()
            self.refresh_dashboard()

    def update_run_panel(self) -> None:
        elapsed = time.monotonic() - self.run_started
        sim_s = self.latest.timestamp_ms / 1000 if self.latest else 0.0
        kind = self.source_combo.currentData()
        text = self.fmt(
            f"زمن التشغيل: {elapsed:.0f} ث  •  زمن الجلسة: {sim_s:.1f} ث",
            f"Run time: {elapsed:.0f} s  •  Session time: {sim_s:.1f} s",
        )
        if kind == "simulation":
            total = SimulationSource.NATURAL_TRIP_MS / 1000
            self.run_progress.setValue(int(min(sim_s / total, 1.0) * 1000))
            self.run_progress.show()
            text += self.fmt(f"  •  طول الرحلة {total:.0f} ث", f"  •  Trip length {total:.0f} s")
        else:
            self.run_progress.hide()
        self.run_time_label.setText(text)

    def show_stats(self, stats: dict[str, Any]) -> None:
        self.session_accepted = int(stats.get("accepted", 0))
        self.dash_samples.setText(
            self.fmt(
                f"العينات المستلمة: {self.session_accepted}",
                f"Samples received: {self.session_accepted}",
            )
        )

    # ------------------------------------------------------------------ dashboard state
    def conn_state(self) -> str:
        if self.device_state in ("RECONNECTING",) and self.running:
            return "reconnecting"
        if self.running:
            if self.session_accepted == 0 and (
                self.latest is None or time.monotonic() - self.last_received > STALE_AFTER_S
            ):
                return "waiting"
            if self.latest is not None and time.monotonic() - self.last_received > STALE_AFTER_S:
                return "lost"
            return "receiving"
        text = getattr(self, "status_text", "")
        if text.startswith("خطأ"):
            return "error"
        if text.startswith("اكتمل"):
            return "ended"
        if text.startswith("متوقف"):
            return "stopped"
        return "idle"

    STATE_VIEW = {
        "idle": ("غير متصل", "idle", "لا توجد جلسة", "اختر مصدر بيانات ثم ابدأ المراقبة."),
        "waiting": (
            "متصل — بانتظار البيانات",
            "warn",
            "تم فتح المصدر",
            "لم تصل عينة بعد؛ قد يستغرق الأمر لحظات.",
        ),
        "receiving": ("يستقبل بيانات", "ok", "المراقبة تعمل", "تُسجَّل القراءات والأحداث محليًا."),
        "lost": ("فُقد الاتصال", "warn", "لم تصل عينات جديدة", "القراءات المعروضة قديمة وليست حية."),
        "reconnecting": (
            "إعادة الاتصال",
            "warn",
            "يجري استعادة الاتصال",
            "تظل القراءات الأخيرة معلّمة بأنها قديمة.",
        ),
        "error": (
            "خطأ في المصدر",
            "danger",
            "توقف المصدر بسبب خطأ",
            "راجع رسالة الخطأ ثم أعد المحاولة من مركز المصادر.",
        ),
        "ended": ("انتهت الجلسة", "info", "اكتمل المصدر", "راجع الأحداث والتقارير المحفوظة."),
        "stopped": (
            "متوقف",
            "idle",
            "أوقفت المراقبة",
            "القراءات المعروضة آخر بيانات مستلمة وليست حية.",
        ),
    }

    def refresh_dashboard(self) -> None:
        state = self.conn_state()
        pill_text, tone, headline, hint = self.STATE_VIEW[state]
        if state == "idle" and self.latest is None and not self.backend_ready:
            pill_text = "جارٍ التهيئة"
            tone = "info"
        for pill in (
            self.conn_pill,
            self.dash_state_pill,
            self.dash_conn_pill,
            self.source_state_pill,
        ):
            pill.set_state(self.t(pill_text), tone)
        self.dash_headline.setText(self.t(headline))
        self.dash_hint.setText(self.t(hint))
        monitoring = self.running
        self.dash_monitor_pill.set_state(
            self.t("المراقبة تعمل" if monitoring else "المراقبة متوقفة"),
            "ok" if monitoring else "idle",
        )
        source = self.latest.source.value if self.latest else self.t("—")
        self.dash_source.setText(self.fmt(f"المصدر: {source}", f"Source: {source}"))
        run_s = time.monotonic() - self.run_started if (self.running and self.run_started) else None
        self.dash_duration.setText(
            self.fmt("مدة التشغيل: —", "Run time: —")
            if run_s is None
            else self.fmt(f"مدة التشغيل: {run_s:.0f} ث", f"Run time: {run_s:.0f} s")
        )
        self.dash_samples.setText(
            self.fmt(
                f"العينات المستلمة: {self.session_accepted}",
                f"Samples received: {self.session_accepted}",
            )
        )
        events_here = [
            e for e in self.event_rows if e.get("session_id") == self.session_id and self.session_id
        ]
        rules_here = [e for e in events_here if event_category(e) == "rule"]
        self.dash_events_count.setText(
            self.fmt(
                f"الأحداث المسجلة: {len(events_here)} (الكل {len(self.event_rows)})",
                f"Recorded events: {len(events_here)} (all {len(self.event_rows)})",
            )
        )
        self.dash_warnings.setText(
            self.fmt(
                f"أحداث القواعد في هذه الجلسة: {len(rules_here)}",
                f"Rule events in this session: {len(rules_here)}",
            )
        )
        last = max(self.event_rows, key=lambda e: e["trigger_ms"]) if self.event_rows else None
        self.dash_last_event.setText(
            self.fmt("آخر حدث: لا يوجد", "Latest event: none")
            if last is None
            else self.fmt(
                f"آخر حدث: {KIND_AR.get(last['kind'], last['kind'])} عند {last['trigger_ms'] / 1000:.1f} ث",
                f"Latest event: {self.t(KIND_AR.get(last['kind'], last['kind']))} at {last['trigger_ms'] / 1000:.1f} s",
            )
        )
        self.dash_report.setEnabled(last is not None)

    def open_latest_report(self) -> None:
        if self.event_rows:
            latest_event = max(self.event_rows, key=lambda e: e["trigger_ms"])
            self.open_event_by_id(str(latest_event["event_id"]))

    # ------------------------------------------------------------------ events view
    def show_events(self, rows: list[dict[str, Any]]) -> None:
        self.event_rows = rows
        selected_id = self.selected_event_id()
        scroll = self.events_table.verticalScrollBar().value()
        text = self.event_search.text().strip().lower()
        wanted = self.event_filter.currentData()
        ordered = sorted(
            rows, key=lambda r: r["trigger_ms"], reverse=self.event_sort.currentData() == "desc"
        )
        visible = []
        for data in ordered:
            if wanted not in (None, "all") and event_category(data) != wanted:
                continue
            title = KIND_AR.get(data["kind"], data["kind"])
            haystack = f"{title} {self.t(title)} {data['event_id']} {data.get('system_ar', '')} {data.get('system_en', '')}".lower()
            if text and text not in haystack:
                continue
            visible.append(data)
        shown = visible[: self.events_shown]
        self.events_table.setUpdatesEnabled(False)
        self.events_table.setRowCount(len(shown))
        category_icons = {
            "rule": make_icon("events", design.palette(self.theme).primary, 18),
            "quality": make_icon("warning", design.palette(self.theme).warning, 18),
            "connection": make_icon("connection", design.palette(self.theme).danger, 18),
            "ml": make_icon("sensors", design.palette(self.theme).info, 18),
        }
        for row, data in enumerate(shown):
            texts = (
                KIND_AR.get(data["kind"], data["kind"]),
                f"{data['trigger_ms'] / 1000:.1f}",
                STATUS_AR.get(data["status"], data["status"]),
                data["event_id"],
                data.get("origin", "LIVE"),
                data.get("system_en" if self.language == "en" else "system_ar", "—"),
                str(data.get("support_count", "—")),
                data.get("checks_en" if self.language == "en" else "checks_ar", "—"),
                data.get("detection_method", "RULE"),
            )
            for column, cell in enumerate(texts):
                item = QTableWidgetItem(self.t(cell))
                item.setToolTip(self.t(cell))
                if column == 0:
                    item.setIcon(category_icons[event_category(data)])
                if column == len(texts) - 1:  # detection method: tooltip states the AI result
                    item.setToolTip(
                        self.t(cell)
                        + "\n"
                        + ai.message(data.get("ai_state", ai.NOT_RECORDED), self.language)
                    )
                self.events_table.setItem(row, column, item)
            self.events_table.setRowHeight(row, 64 if data["kind"] in RULES else 36)
        self.events_table.setUpdatesEnabled(True)
        if selected_id:
            for row, data in enumerate(shown):
                if data["event_id"] == selected_id:
                    self.events_table.selectRow(row)
                    break
        self.events_table.verticalScrollBar().setValue(scroll)
        more = len(visible) > len(shown)
        self.events_more.setVisible(more)
        self.events_count.setText(
            self.fmt(
                f"المعروض {len(shown)} من {len(visible)} (الإجمالي {len(rows)})",
                f"Shown {len(shown)} of {len(visible)} (total {len(rows)})",
            )
        )
        self.update_events_empty()
        self.refresh_dashboard()

    def selected_event_id(self) -> str:
        row = self.events_table.currentRow()
        item = self.events_table.item(row, 3) if row >= 0 else None
        return item.text() if item is not None else ""

    def open_event(self, row: int, column: int) -> None:
        item = self.events_table.item(row, 3) if row >= 0 else None
        if item is not None:
            self.open_event_by_id(item.text())

    def open_event_by_id(self, event_id: str, navigate: bool = True) -> None:
        self._navigate_on_report = navigate
        self.current_event = next((e for e in self.event_rows if e["event_id"] == event_id), None)
        self.report_status_pill.set_state(self.t("جارٍ تحميل التقرير…"), "info")
        self.update_report_header()
        self.worker.submit("report", event_id=event_id, language=self.language)

    def update_report_header(self) -> None:
        event = self.current_event
        if event is None:
            return
        title = KIND_AR.get(event["kind"], event["kind"])
        self.report_title.setText(self.t(title))
        status = STATUS_AR.get(event["status"], event["status"])
        partial = event["status"] != "COMPLETE"
        self.report_status_pill.set_state(
            self.fmt(f"التسجيل: {status}", f"Recording: {self.t(status)}"),
            "warn" if partial else "ok",
            self.t("تسجيل جزئي: لا تتوفر 30 ث كاملة قبل الكشف أو بعده" if partial else ""),
        )
        category = {
            "rule": "كشف بالقواعد",
            "quality": "جودة البيانات",
            "connection": "اتصال",
            "ml": "تحليل ML استشاري",
        }[event_category(event)]
        self.report_meta.setText(
            self.fmt(
                f"النوع: {category}  •  لحظة الكشف {event['trigger_ms'] / 1000:.1f} ث  •  الأصل: {event.get('origin', 'LIVE')}",
                f"Type: {self.t(category)}  •  Detected at {event['trigger_ms'] / 1000:.1f} s  •  Origin: {event.get('origin', 'LIVE')}",
            )
        )
        state = event.get("ai_state", ai.NOT_RECORDED)
        analyzed_anomalous = "ANOMALOUS" in str(state)
        self.report_ai_pill.set_state(
            self.t(
                "AI (استشاري): نمط غير معتاد"
                if analyzed_anomalous
                else "AI (استشاري): " + ("نمط معتاد" if "NORMAL" in str(state) else "لا نتيجة")
            ),
            "warn" if analyzed_anomalous else "info",
            ai.message(state, self.language),
        )
        self.report_ai_note.setText(
            ai.message(state, self.language)
            + "  —  "
            + self.t("تحليل ML استشاري وتفسيره لا يثبتان تلف قطعة.")
        )

    def show_report(self, text: str) -> None:
        self.report_text.setPlainText(text)
        if self._navigate_on_report:
            self.navigation.setCurrentRow(4)
        self._navigate_on_report = True

    def show_ai(self, result: dict[str, Any]) -> None:
        decision = result.get("decision", "UNAVAILABLE")
        self.ai_decision = str(decision)
        labels = {
            "NORMAL": "نشط — نمط معتاد",
            "ANOMALOUS": "نشط — نمط غير معتاد",
            "UNAVAILABLE": "غير متاح",
            "INSUFFICIENT_DATA": "بيانات غير كافية",
        }
        unavailable = {
            "MODEL_NOT_LOADED": ("غير متاح — النموذج لم يُحمّل", "Unavailable — model not loaded"),
            "INFERENCE_FAILED": ("غير متاح — خطأ تقني", "Unavailable — technical error"),
            "DISABLED": ("غير مفعّل", "Not enabled"),
        }
        state = result.get("state")
        if decision == "UNAVAILABLE" and state in unavailable:
            text = unavailable[state][0 if self.language == "ar" else 1]
        else:
            text = labels.get(decision, decision) if self.language == "ar" else decision
        score = result.get("score")
        version = result.get("model_version")
        self.ai_label.setText(
            "AI: "
            + text
            + (f" | {score:.3f}" if score is not None else "")
            + (f" | {version}" if version else "")
        )
        self.ai_label.setToolTip(str(result.get("reason", "")))
        tone = {"NORMAL": "ok", "ANOMALOUS": "warn", "INSUFFICIENT_DATA": "info"}.get(
            str(decision), "idle"
        )
        pill = {
            "NORMAL": "AI: نمط معتاد (استشاري)",
            "ANOMALOUS": "AI: نمط غير معتاد (استشاري)",
            "INSUFFICIENT_DATA": "AI: بيانات غير كافية",
        }.get(str(decision), "AI غير متاح" if state != "DISABLED" else "AI غير مفعّل")
        self.ai_pill_state = (pill, tone, str(result.get("reason", "")))
        self.render_ai_pills()

    def render_ai_pills(self) -> None:
        text, tone, tip = self.ai_pill_state
        for p in (self.ai_pill, self.dash_ai_pill):
            p.set_state(self.t(text), tone, tip)

    def show_error(self, message: str) -> None:
        self.error_message = message
        if self.source_combo.isEnabled():
            self.verify_button.setEnabled(True)
        self.error_label.setText(self.t(message))
        self.error_label.show()
        self.notify("error", message, sticky=True)

    def on_worker_finished(self) -> None:
        if self.closing:
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker.isRunning():
            self.closing = True
            self.start_button.setEnabled(False)
            self.set_status("جارٍ حفظ التسجيل وإغلاق الموارد…")
            self.worker.shutdown()
            event.ignore()
        else:
            self.age_timer.stop()
            event.accept()

    def t(self, text: str) -> str:
        return translate(text, self.language)

    def fmt(self, arabic: str, english: str) -> str:
        """Pick a fully formatted sentence by language (avoids fragment translation of numbers)."""
        return arabic if self.language == "ar" else english

    def legacy_selected(self) -> None:
        if self.scenario_combo.currentIndex() > 0:
            self.family_combo.setCurrentIndex(0)
            self.mode_combo.setCurrentIndex(3)

    def family_changed(self) -> None:
        multi = self.family_combo.currentData() == "multisensor"
        self.fault_duration.setMaximum(90 if multi else 60)
        self.fault_duration.setValue(35 if multi else 5)
        self.max_faults_input.setMaximum(2 if multi else 3)
        if multi and self.mode_combo.currentData() == "LEGACY":
            self.mode_combo.setCurrentIndex(0)
        self.update_source_fields()

    def update_source_fields(self) -> None:
        kind, mode = self.source_combo.currentData(), self.mode_combo.currentData()
        sim, device = kind == "simulation", kind == "device_simulator"
        multi = self.family_combo.currentData() == "multisensor"
        self.source_hint.setText(self.t(SOURCE_HINTS.get(str(kind), "")))
        visible = {
            self.host_input: kind == "network",
            self.network_port: kind == "network",
            self.mode_combo: sim,
            self.family_combo: sim,
            self.scenario_combo: sim and mode == "LEGACY",
            self.fault_list: sim and mode == "FAULT_INJECTION" and not multi,
            self.multisensor_list: sim and mode == "FAULT_INJECTION" and multi,
            self.scenario_info: sim and mode == "FAULT_INJECTION" and multi,
            self.variant_combo: sim
            and mode == "FAULT_INJECTION"
            and multi
            and self.multisensor_list.item(6).checkState() == Qt.CheckState.Checked,
            self.fault_start: sim and mode == "FAULT_INJECTION",
            self.fault_duration: sim and mode == "FAULT_INJECTION",
            self.severity_input: sim and mode == "FAULT_INJECTION",
            self.seed_input: sim or device,
            self.max_faults_input: sim and mode == "RANDOM_FAULTS",
            self.normal_probability: sim and mode == "RANDOM_FAULTS",
            self.speed_combo: sim or device,
            self.path_input: kind in ("replay", "protocol_file"),
            self.browse_button: kind in ("replay", "protocol_file"),
            self.port_combo: kind == "serial",
            self.refresh_ports: kind == "serial",
        }
        for control, show in visible.items():
            self.source_form.setRowVisible(control, show)
        if self.source_combo.isEnabled():
            self.connection_details.setText(self.t("DISCONNECTED"))

    def source_arguments(self) -> dict[str, Any]:
        kind = self.source_combo.currentData()
        args: dict[str, Any] = {"source": kind}
        if self.ai_enabled.isChecked():
            args["ai_enabled"] = True
        if kind == "simulation":
            mode = self.mode_combo.currentData()
            args.update(seed=self.seed_input.value(), speed=self.speed_combo.currentData())
            multi = self.family_combo.currentData() == "multisensor"
            if multi:
                args["scenario_family"] = "multisensor"
                if mode == "LEGACY":
                    raise ValueError(self.t("اختر وضعًا مناسبًا للمحاكاة المترابطة"))
            if mode == "LEGACY":
                args["scenario"] = self.scenario_combo.currentData()
            else:
                args["mode"] = mode
            if mode == "FAULT_INJECTION":
                from dataclasses import asdict

                if multi:
                    args["scenarios"] = [
                        asdict(
                            ScenarioInstance(
                                str(self.multisensor_list.item(i).data(Qt.ItemDataRole.UserRole)),
                                self.fault_start.value() * 1000,
                                self.fault_duration.value() * 1000,
                                self.severity_input.value(),
                                self.variant_combo.currentData()
                                if self.multisensor_list.item(i).data(Qt.ItemDataRole.UserRole)
                                == "S07"
                                else "default",
                            )
                        )
                        for i in range(self.multisensor_list.count())
                        if self.multisensor_list.item(i).checkState() == Qt.CheckState.Checked
                    ]
                    if not args["scenarios"]:
                        raise ValueError(self.t("اختر سيناريو مترابطًا واحدًا على الأقل"))
                    self.preferences.setValue("seed", self.seed_input.value())
                    return args

                args["faults"] = [
                    asdict(
                        FaultInstance(
                            str(self.fault_list.item(i).data(Qt.ItemDataRole.UserRole)),
                            self.fault_start.value() * 1000,
                            self.fault_duration.value() * 1000,
                            self.severity_input.value(),
                        )
                    )
                    for i in range(self.fault_list.count())
                    if self.fault_list.item(i).checkState() == Qt.CheckState.Checked
                ]
                if not args["faults"]:
                    raise ValueError(self.t("اختر خللًا واحدًا على الأقل"))
            if mode == "RANDOM_FAULTS":
                args.update(
                    max_faults=self.max_faults_input.value(),
                    normal_probability=self.normal_probability.value(),
                )
        elif kind == "device_simulator":
            args.update(seed=self.seed_input.value(), speed=self.speed_combo.currentData())
        elif kind in ("replay", "protocol_file"):
            if not self.path_input.text().strip():
                raise ValueError(
                    self.t(
                        "اختر ملف إعادة التشغيل (Replay) أولًا"
                        if kind == "replay"
                        else "اختر ملف البروتوكول أولًا"
                    )
                )
            args["path"] = self.path_input.text()
        elif kind == "serial":
            args["port"] = self.port_input.text()
        elif kind == "network":
            args.update(host=self.host_input.text(), network_port=self.network_port.value())
        self.preferences.setValue("seed", self.seed_input.value())
        self.preferences.setValue("last_source", str(kind))
        self.preferences.setValue("ai_enabled", "true" if self.ai_enabled.isChecked() else "false")
        self.preferences.sync()
        return args

    def verify_source(self) -> None:
        try:
            self.verify_button.setEnabled(False)
            self.connection_details.setText(self.t("CONNECTING"))
            self.source_state_pill.set_state(self.t("جارٍ الاتصال"), "info")
            self.worker.submit("verify", **self.source_arguments())
        except ValueError as exc:
            self.verify_button.setEnabled(True)
            self.show_error(str(exc))
            self.refresh_dashboard()

    def show_ports(self, ports: list[str]) -> None:
        current = self.port_input.text()
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        self.port_combo.setCurrentText(current or (ports[0] if ports else ""))
        self.connection_details.setText(self.t("PORT_AVAILABLE" if ports else "DISCONNECTED"))
        if not ports:
            self.notify("info", "لا توجد منافذ تسلسلية ظاهرة في النظام")

    def show_verification(self, result: dict[str, Any]) -> None:
        self.verify_button.setEnabled(True)
        stages = " → ".join(self.t(s) for s in result.get("stages", []))
        self.connection_details.setText(
            self.t("فحص ناجح" if result.get("ok") else "فحص غير ناجح")
            + "\n"
            + stages
            + "\n"
            + str(result.get("error", ""))
            + (
                "\nFirmware: "
                + str(result["firmware_version"])
                + " | JSONL: "
                + str(result.get("protocol_version", "—"))
                if result.get("firmware_version")
                else ""
            )
        )
        self.connection_details.setToolTip(json.dumps(result, ensure_ascii=False, indent=2))
        ok = bool(result.get("ok"))
        self.source_state_pill.set_state(
            self.t("فحص ناجح — جاهز للبدء" if ok else "فحص غير ناجح"), "ok" if ok else "danger"
        )
        if ok:
            self.notify("success", "نجح فحص المصدر")

    def show_device(self, info: dict[str, Any]) -> None:
        self.device_state = str(info.get("state", ""))
        if self.source_combo.currentData() in (
            "serial",
            "protocol_file",
            "device_simulator",
            "network",
        ):
            capabilities = info.get("capabilities", {})
            self.connection_details.setText(
                self.t(str(info["state"]))
                + " | "
                + str(info.get("device_id") or "—")
                + "\nFirmware: "
                + str(info.get("firmware_version") or "—")
                + " | JSONL: "
                + str(info.get("protocol_version") or "—")
                + " | ms: "
                + str(info.get("last_timestamp_ms", "—"))
                + "\n"
                + str(info.get("source") or "—")
                + f" | Sensors: {len(capabilities.get('sensors', []))}"
                + f" | CAN: {capabilities.get('can', False)}"
                + f" | MicroSD: {capabilities.get('microsd', False)}"
                + f" | Event upload: {capabilities.get('event_upload', False)}"
            )

    def show_simulation(self, result: dict[str, Any]) -> None:
        # Test ground truth is shown separately; it is never diagnostic evidence.
        lines = [
            self.t("جدول الحقن ونتائج الكشف — تقييم اختباري فقط"),
            f"Seed={result['seed']} | {result['schedule_version']}",
        ]
        lines.extend(
            f"{f['start_ms'] / 1000:g}s / {f['duration_ms'] / 1000:g}s | "
            f"{f['fault_id']} | {self.t(f['status'])} | "
            f"M1={'RULE' if f['detectable_in_m1'] else 'DISPLAY ONLY'}"
            for f in result["faults"]
        )
        lines.append(self.t("أحداث بلا تطابق: ") + str(len(result["unmatched_events"])))
        for fault in result["faults"]:
            for detected in fault.get("detections", []):
                lines.append(
                    f"DoctorCAR: {detected['pattern']} | "
                    f"{len(detected['evidence'])} " + self.t("أدلة داعمة")
                )
        if "false_positive_events_on_known_normal" in result:
            lines.append(
                self.t("إنذارات في فترات طبيعية معلومة: ")
                + str(len(result["false_positive_events_on_known_normal"]))
            )
            lines.append(self.t("تطابق النمط ليس إثبات السبب الميكانيكي"))
        self.simulation_summary.setPlainText("\n".join(lines))

    def set_running(self, running: bool) -> None:
        was_running = self.running
        self.running = running
        self.ai_enabled.setEnabled(not running)
        self.start_button.setEnabled(not running and self.backend_ready)
        self.stop_button.setEnabled(running)
        self.dash_start.setEnabled(not running and self.backend_ready)
        self.dash_stop.setEnabled(running)
        self.source_combo.setEnabled(not running)
        self.verify_button.setEnabled(not running)
        for row in range(1, self.source_form.rowCount()):
            item = self.source_form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            control = item.widget() if item else None
            if control:
                control.setEnabled(not running)
        if running:
            self.simulation_summary.clear()
            self.run_started = time.monotonic()
            self.session_accepted = 0
            self.session_id = ""
            self.summary_card.hide()
            self.dash_samples.setText(self.t("العينات المستلمة: 0"))
            for tile in [*self.sensor_tiles.values(), *self.cards.values()]:
                tile.last_value = None
                set_property(tile, "state", "active")
            self.update_run_panel()
        elif was_running:
            self.run_progress.hide()
            self.run_time_label.setText("")
            self.finish_summary()
        self.refresh_dashboard()

    def finish_summary(self) -> None:
        status = getattr(self, "status_text", "")
        if status.startswith("خطأ"):
            return
        events_here = [e for e in self.event_rows if e.get("session_id") == self.session_id]
        self.finished_summary = {
            "elapsed": time.monotonic() - self.run_started if self.run_started else 0.0,
            "sim_s": self.latest.timestamp_ms / 1000 if self.latest else 0.0,
            "samples": self.session_accepted,
            "events": len(events_here),
        }
        self.render_summary()
        self.summary_card.show()

    def render_summary(self) -> None:
        data = self.finished_summary
        if data is None:
            return
        saved_ar = "اكتمل — " if data["samples"] else "لا توجد عينات — "
        saved_en = "done — " if data["samples"] else "no samples — "
        self.summary_text.setText(
            self.fmt(
                f"مدة الجلسة: {data['sim_s']:.1f} ث (زمن الجلسة) • {data['elapsed']:.0f} ث (زمن التشغيل)\n"
                f"العينات المستلمة: {data['samples']}\n"
                f"الأحداث المسجلة في الجلسة: {data['events']}\n"
                f"الحفظ: {saved_ar}البيانات محفوظة في قاعدة البيانات المحلية",
                f"Session duration: {data['sim_s']:.1f} s (session time) • {data['elapsed']:.0f} s (run time)\n"
                f"Samples received: {data['samples']}\n"
                f"Events recorded in the session: {data['events']}\n"
                f"Saving: {saved_en}data is stored in the local database",
            )
        )

    # ------------------------------------------------------------------ text capture / preferences
    def _capture_texts(self) -> None:
        self.static_texts: list[tuple[Any, str]] = []
        for control in self.findChildren(QLabel) + self.findChildren(QPushButton):
            if (
                control in (self.status_label, self.error_label)
                or control.property("dynamic")
                or isinstance(control, StatusPill)
                or isinstance(control.parent(), (MetricTile, ToastHost))
            ):
                continue
            if isinstance(control, QLabel) and control.pixmap() is not None and not control.text():
                continue
            self.static_texts.append((control, control.text()))
        self.combo_texts = [
            (c, [c.itemText(i) for i in range(c.count())])
            for c in self.findChildren(QComboBox)
            if c is not self.port_combo
        ]
        self.nav_texts = [self.navigation.item(i).text() for i in range(self.navigation.count())]
        self.headers = []
        for table in (self.sensor_table, self.events_table):
            originals = []
            for i in range(table.columnCount()):
                header = table.horizontalHeaderItem(i)
                assert header is not None
                originals.append(header.text())
            self.headers.append((table, originals))
        self.placeholder_texts = [(c, c.placeholderText()) for c in self.findChildren(QLineEdit)]
        self.checkbox_texts = [(c, c.text()) for c in self.findChildren(QCheckBox)]
        self.tooltip_texts = [
            (c, c.toolTip())
            for c in self.findChildren(QWidget)
            if c.toolTip() and not isinstance(c, (StatusPill, QListWidget))
        ]
        self.empty_states = self.findChildren(EmptyState)
        self.empty_originals = [
            (e, e.title.text(), e.hint.text(), e.action.text() if e.action else "")
            for e in self.empty_states
        ]

    def apply_preferences(self) -> None:
        self.language = str(self.language_combo.currentData())
        self.theme = str(self.theme_combo.currentData())
        self.zoom = int(self.zoom_combo.currentData())
        Motion.user_enabled = not self.reduce_motion.isChecked()
        self.preferences.setValue("language", self.language)
        self.preferences.setValue("theme", self.theme)
        self.preferences.setValue("zoom", self.zoom)
        self.preferences.setValue("reduce_motion", "true" if not Motion.user_enabled else "false")
        self.preferences.setValue(
            "remember_source", "true" if self.remember_source.isChecked() else "false"
        )
        self.preferences.sync()
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if self.language == "ar"
            else Qt.LayoutDirection.LeftToRight
        )
        self.report_text.setLayoutDirection(self.layoutDirection())
        self.simple_report_text.setLayoutDirection(self.layoutDirection())
        self.setWindowTitle(self.t("DoctorCAR | المراقبة والتسجيل التجريبي"))
        self.setStyleSheet(design.build_stylesheet(self.theme, self.zoom / 100.0))
        colors = design.palette(self.theme)
        self.nav_delegate.theme = self.theme
        self.nav_delegate.icons = {
            str(i): make_icon(name, colors.sidebar_muted, 22) for i, name in enumerate(NAV_ICONS)
        }
        self.nav_delegate.icons_active = {
            str(i): make_icon(name, colors.sidebar_text, 22) for i, name in enumerate(NAV_ICONS)
        }
        self.brand_mark.setPixmap(make_icon("sensors", colors.primary, 30).pixmap(30, 30))
        self.toasts.theme = self.theme
        self.timeline.theme = self.theme
        self.time_plot.set_theme(self.theme)
        for empty in self.empty_states:
            empty.apply_theme(self.theme)
        for i, name in enumerate(NAV_NAMES):
            self.navigation.item(i).setToolTip(self.t(name))
        for control, original in self.static_texts:
            control.setText(self.t(original))
        for combo_box, originals_ in self.combo_texts:
            for i, original in enumerate(originals_):
                combo_box.setItemText(i, self.t(original))
        for checkbox, original in self.checkbox_texts:
            checkbox.setText(self.t(original))
        self.ai_enabled.setText(
            "‏تفعيل مراقبة ⁦AI⁩ التجريبية"
            if self.language == "ar"
            else "Enable experimental AI monitoring"
        )
        for empty, title, hint, action in self.empty_originals:
            empty.set_texts(self.t(title), self.t(hint), self.t(action))
        self.set_status(getattr(self, "status_text", "تهيئة التخزين المحلي…"), announce=False)
        if hasattr(self, "error_message"):
            self.error_label.setText(self.t(self.error_message))
        for i, original in enumerate(self.nav_texts):
            self.navigation.item(i).setText(self.t(original))
        self.page_title.setText(self.t(NAV_NAMES[max(0, self.navigation.currentRow())]))
        for table, originals in self.headers:
            table.setHorizontalHeaderLabels([self.t(x) for x in originals])
        for control_, original in self.placeholder_texts:
            control_.setPlaceholderText(self.t(original))
        for i, fault in enumerate(FAULTS.values()):
            self.fault_list.item(i).setText(
                fault.arabic_name if self.language == "ar" else fault.english_name
            )
            self.fault_list.item(i).setToolTip(
                f"{fault.description}\n{fault.expected_evidence}\n"
                f"M1: {', '.join(fault.detected_by) or 'DISPLAY ONLY'}"
                if self.language == "ar"
                else f"{fault.english_name} | {fault.behavior}\n"
                f"Signals: {', '.join(fault.sensors)}\n"
                f"M1: {', '.join(fault.detected_by) or 'DISPLAY ONLY; no detection rule'}"
            )
        for i, definition in enumerate(SCENARIOS_MS.values()):
            self.multisensor_list.item(i).setText(
                definition.scenario_id
                + " — "
                + (definition.arabic_name if self.language == "ar" else definition.english_name)
            )
        self.show_scenario_info(self.multisensor_list.currentRow())
        for row, spec in enumerate(REGISTRY.all()):
            item = self.sensor_table.item(row, 0)
            assert item is not None
            item.setText(self.t(spec.arabic_name))
            tile = self.sensor_tiles[spec.sensor_id]
            tile.name_label.setText(self.t(spec.arabic_name))
            if not self.latest:
                status_item = self.sensor_table.item(row, 4)
                assert status_item is not None
                status_item.setText(self.t("لم تصل بيانات"))
                tile.quality.set_state(self.t("بلا بيانات"), "idle")
            dash = self.cards.get(spec.sensor_id)
            if dash is not None:
                dash.name_label.setText(self.t(spec.arabic_name))
                if not self.latest:
                    dash.quality.set_state(self.t("بلا بيانات"), "idle")
        if self.report_text.toPlainText() in (
            "اختر حدثًا من السجل لعرض تقريره.",
            "Select an event from history to view its report.",
        ):
            self.report_text.setPlainText(self.t("اختر حدثًا من السجل لعرض تقريره."))
        if self.latest:
            received = self.last_received
            self.show_sample(self.latest)  # DEF-011: re-render language-dependent cells
            self.last_received = received
            self.update_age()
        self.update_source_fields()
        self.set_sidebar_collapsed(self.sidebar_collapsed)
        self.show_events(self.event_rows)
        if self.current_event is not None:
            # re-render the open report in the new language without leaving the current page
            self.open_event_by_id(str(self.current_event["event_id"]), navigate=False)
        if self.current_event is None:
            self.report_title.setText(self.t("اختر حدثًا من السجل"))
        self.update_report_header()
        self.apply_sensor_filter()
        for widget, tip in self.tooltip_texts:
            widget.setToolTip(self.t(tip))
        self.name_form_fields()
        self.render_ai_pills()
        self.render_summary()
        if self.running:
            self.update_run_panel()
        self.refresh_dashboard()

    def set_status(self, message: str, announce: bool = True) -> None:
        self.status_text = message
        self.status_label.setText(self.t(message))
        if announce:
            if message.startswith("اكتمل"):
                self.notify("info", "انتهت الجلسة — اكتمل المصدر وحُفظت البيانات")
            elif message.startswith("خطأ"):
                self.notify("warning", "فُقد اتصال المصدر أو توقف؛ القراءات المعروضة ليست حية")
            elif message.startswith("تم تصدير"):
                self.notify("success", "تم تصدير الجلسة إلى ملف Replay")
        if hasattr(self, "dash_headline"):
            self.refresh_dashboard()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
