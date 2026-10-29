from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLocale, QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
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
from doctorcar.ui.localization import translate
from doctorcar.ui.timeseries_plot import TimeSeriesPlot
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


def ltr(text: str) -> str:
    """Keep negative numbers, technical IDs and units intact inside RTL paragraphs."""
    return "\u2066" + text + "\u2069"


class TechnicalDelegate(QStyledItemDelegate):
    def displayText(self, value: Any, locale: QLocale | QLocale.Language) -> str:
        # Change presentation only: the item retains its unmodified database ID.
        return ltr(str(value))


STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 14px; color: #173042; background: #f4f7f8; }
QWidget#sidebar { background: #102c3a; border-radius: 16px; }
QLabel#brand { font-size: 26px; font-weight: 700; color: #ecfaf7; background: transparent; }
QLabel#sidebarNote { color: #accccf; background: transparent; font-size: 12px; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#eyebrow { color: #087f79; font-size: 13px; font-weight: 600; }
QLabel#notice { background: #fff2d8; color: #715018; border-radius: 10px; padding: 12px; }
QLabel#error { color: #a22b35; background: #fff0ef; border-radius: 8px; padding: 8px; }
QLabel#card { background: white; border: 1px solid #dbe5e9; border-radius: 14px;
              padding: 22px; font-size: 23px; min-height: 90px; }
QPushButton { background: #087f79; color: white; padding: 11px 20px; border-radius: 8px; }
QPushButton:hover { background: #096a67; }
QPushButton:disabled { background: #aec5c8; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                     background: white; padding: 9px; border: 1px solid #cbdade;
                     border-radius: 7px; }
QListWidget { background: transparent; color: #dcebec; border: none; outline: none; }
QListWidget::item { padding: 15px 12px; margin: 3px; border-radius: 9px; }
QListWidget::item:selected { background: #1d535b; color: white; }
QListWidget#faultList::item { padding: 4px 8px; margin: 1px; min-height: 25px; }
QTableWidget, QTextEdit { background: white; border: 1px solid #dbe5e9; border-radius: 10px;
                         gridline-color: #edf2f4; selection-background-color: #d9efed; }
QHeaderView::section { background: #e7eff1; border: none; padding: 12px; font-weight: 600; }
"""


def page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(18)
    label = QLabel(title)
    label.setObjectName("title")
    layout.addWidget(label)
    note = QLabel(subtitle)
    note.setWordWrap(True)
    layout.addWidget(note)
    return widget, layout


class MainWindow(QMainWindow):
    def __init__(self, database: Path) -> None:
        super().__init__()
        self.preferences = QSettings(
            str(database.resolve().with_suffix(".settings.ini")), QSettings.Format.IniFormat
        )
        self.language = str(self.preferences.value("language", "ar"))
        self.theme = str(self.preferences.value("theme", "light"))
        self.event_rows: list[dict[str, Any]] = []
        self.setWindowTitle("DoctorCAR | المراقبة والتسجيل التجريبي")
        self.setMinimumSize(980, 680)
        self.resize(1240, 820)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(STYLE)
        self.latest: Sample | None = None
        self.last_received = 0.0
        self.backend_ready = False
        self.closing = False
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(22)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(225)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 24, 16, 20)
        brand = QLabel("DoctorCAR")
        brand.setObjectName("brand")
        brand.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        side.addWidget(brand)
        tag = QLabel("مراقبة • أدلة • فهم")
        tag.setObjectName("sidebarNote")
        side.addWidget(tag)
        self.navigation = QListWidget()
        self.navigation.addItems(
            [
                "لوحة التحكم",
                "مركز المصادر",
                "قراءات الحساسات",
                "سجل الأحداث",
                "تفاصيل الحدث والتقرير",
                "الإعدادات",
            ]
        )
        side.addWidget(self.navigation, 1)
        version = QLabel("الإصدار التأسيسي M1\nلا اتصال فعلي بالمركبة")
        version.setObjectName("sidebarNote")
        side.addWidget(version)
        outer.addWidget(sidebar)
        content = QVBoxLayout()
        outer.addLayout(content, 1)
        eyebrow = QLabel("مختبر المراقبة  /  DOCTORCAR M1")
        eyebrow.setObjectName("eyebrow")
        content.addWidget(eyebrow)
        self.notice = QLabel("بيانات محاكاة واختبار فقط — النتائج ليست تشخيصًا قاطعًا لعطل ميكانيكي")
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        content.addWidget(self.notice)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        self._dashboard()
        self._sources()
        self._sensors()
        self._events()
        self._report()
        self._settings(database)
        self.status_label = QLabel("تهيئة التخزين المحلي…")
        content.addWidget(self.status_label)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        content.addWidget(self.error_label)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.worker = BackendWorker(database)
        self.worker.snapshot.connect(self.show_sample)
        self.worker.events_changed.connect(self.show_events)
        self.worker.report_ready.connect(self.show_report)
        self.worker.simple_report_ready.connect(self.simple_report_text.setPlainText)
        self.worker.ai_changed.connect(self.show_ai)
        self.worker.plot_ready.connect(lambda data: self.time_plot.set_series(data, self.language))
        self.worker.status_changed.connect(self.set_status)
        self.worker.error.connect(self.show_error)
        self.worker.initialized.connect(self.on_ready)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.running_changed.connect(self.set_running)
        self.worker.ports_changed.connect(self.show_ports)
        self.worker.verification_changed.connect(self.show_verification)
        self.worker.device_changed.connect(self.show_device)
        self.worker.simulation_changed.connect(self.show_simulation)
        self._capture_texts()
        self.apply_preferences()
        self.worker.start()
        self.age_timer = QTimer(self)
        self.age_timer.timeout.connect(self.update_age)
        self.age_timer.start(500)

    def _dashboard(self) -> None:
        widget, layout = page(
            "كل قراءة في سياقها", "تابع مصدر البيانات، ثم راجع الأحداث وأدلتها المسجلة."
        )
        grid = QGridLayout()
        self.cards: dict[str, QLabel] = {}
        for i, sensor_id in enumerate(("RPM", "SPEED", "COOLANT_TEMP", "CONTROL_MODULE_VOLTAGE")):
            spec = REGISTRY.get(sensor_id)
            card = QLabel(f"{spec.arabic_name}\n— {spec.unit}")
            card.setObjectName("card")
            self.cards[sensor_id] = card
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid)
        self.context = QLabel("لم تبدأ جلسة بعد. اختر المحاكاة من مركز المصادر.")
        self.context.setWordWrap(True)
        layout.addWidget(self.context)
        self.age = QLabel("لا توجد قراءة")
        layout.addWidget(self.age)
        self.ai_label = QLabel("AI — Unavailable")
        self.ai_label.setWordWrap(True)
        layout.addWidget(self.ai_label)
        self.simulation_summary = QTextEdit()
        self.simulation_summary.setReadOnly(True)
        self.simulation_summary.setMaximumHeight(165)
        self.simulation_summary.setPlaceholderText("جدول الحقن ونتائج الكشف — تقييم اختباري فقط")
        layout.addWidget(self.simulation_summary)
        go = QPushButton("اختيار مصدر البيانات")
        go.clicked.connect(lambda: self.navigation.setCurrentRow(1))
        layout.addWidget(go)
        layout.addStretch()
        self.pages.addWidget(widget)

    def _sources(self) -> None:
        widget, layout = page(
            "مركز المصادر", "جلسة واحدة تغذي جميع الصفحات. لا يُفتح أي منفذ تلقائيًا."
        )
        form = QFormLayout()
        self.ai_enabled = QCheckBox("تفعيل مراقبة AI التجريبية")
        layout.addWidget(self.ai_enabled)
        self.source_combo = QComboBox()
        self.source_combo.addItem("محاكاة — SIMULATION", "simulation")
        self.source_combo.addItem("إعادة تشغيل ملف — REPLAY", "replay")
        self.source_combo.addItem("محاكي الجهاز / ملف البروتوكول", "protocol_file")
        self.source_combo.addItem("جهاز DoctorCAR تجريبي — USB Serial", "serial")
        self.source_combo.addItem(
            "ذاكرة جهاز محاكاة — SIMULATED DEVICE HISTORY", "device_simulator"
        )
        self.source_combo.addItem("جهاز DoctorCAR عبر الشبكة — تجريبي", "network")
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
        self.variant_combo = QComboBox()
        for title, value in (
            ("فقد متقطع", "dropout"),
            ("قيمة غير منطقية", "implausible"),
            ("ثبات مشتبه", "flatline"),
        ):
            self.variant_combo.addItem(title, value)
        for label, value in (
            ("رحلة طبيعية", "NORMAL"),
            ("حقن أعطال محددة", "FAULT_INJECTION"),
            ("أعطال عشوائية كل 30 ثانية", "RANDOM_FAULTS"),
            ("سيناريو M1 السابق", "LEGACY"),
        ):
            self.mode_combo.addItem(label, value)
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
        self.refresh_ports = QPushButton("تحديث المنافذ")
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
        self.max_faults_input = QSpinBox()
        self.max_faults_input.setRange(1, 3)
        self.max_faults_input.setValue(3)
        self.normal_probability = QDoubleSpinBox()
        self.normal_probability.setRange(0, 1)
        self.normal_probability.setSingleStep(0.05)
        self.normal_probability.setValue(0.25)
        browse = QPushButton("اختيار ملف البيانات")
        browse.clicked.connect(self.choose_replay)
        form.addRow("المصدر", self.source_combo)
        form.addRow("عنوان الجهاز المحلي", self.host_input)
        form.addRow("منفذ الشبكة", self.network_port)
        form.addRow("عائلة المحاكاة", self.family_combo)
        form.addRow("نوع المحاكاة", self.mode_combo)
        form.addRow("سيناريو المحاكاة", self.scenario_combo)
        form.addRow("الأعطال المختارة", self.fault_list)
        form.addRow("السيناريوهات المترابطة", self.multisensor_list)
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
        form_widget = QWidget()
        form_widget.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll, 1)
        self.verify_button = QPushButton("فحص المصدر / الاتصال")
        self.verify_button.clicked.connect(self.verify_source)
        layout.addWidget(self.verify_button)
        self.connection_details = QLabel("DISCONNECTED")
        self.connection_details.setWordWrap(True)
        layout.addWidget(self.connection_details)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("بدء الجلسة")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_source)
        stop = QPushButton("إيقاف وحفظ المتاح")
        self.stop_button = stop
        stop.clicked.connect(lambda: self.worker.submit("stop"))
        export = QPushButton("تصدير الجلسة لـ Replay")
        export.clicked.connect(self.export_replay)
        buttons.addWidget(self.start_button)
        buttons.addWidget(stop)
        buttons.addWidget(export)
        layout.addLayout(buttons)
        note = QLabel(
            "تسريع العرض يحافظ على زمن العينات ونافذة 30 ثانية.\n"
            "الاتصال الحقيقي بـ OBD وCAN وMicroSD غير منفذ في M1."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.pages.addWidget(widget)
        self.source_combo.currentIndexChanged.connect(self.update_source_fields)
        self.mode_combo.currentIndexChanged.connect(self.update_source_fields)
        self.family_combo.currentIndexChanged.connect(self.family_changed)
        self.multisensor_list.itemChanged.connect(self.update_source_fields)
        self.scenario_combo.currentIndexChanged.connect(self.legacy_selected)
        self.update_source_fields()

    def _sensors(self) -> None:
        widget, layout = page(
            "قراءات الحساسات", "السجل المركزي يحدد الأسماء والوحدات؛ DTC معلومات تشخيصية."
        )
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
        for row, spec in enumerate(REGISTRY.all()):
            for col, text in enumerate(
                (spec.arabic_name, ltr(spec.sensor_id), "—", ltr(spec.unit), "لم تصل بيانات")
            ):
                self.sensor_table.setItem(row, col, QTableWidgetItem(text))
        layout.addWidget(self.sensor_table)
        self.pages.addWidget(widget)

    def _events(self) -> None:
        widget, layout = page(
            "سجل الأحداث", "الأحداث محفوظة محليًا وتبقى متاحة بعد إعادة تشغيل التطبيق."
        )
        refresh = QPushButton("تحديث السجل")
        refresh.clicked.connect(lambda: self.worker.submit("refresh"))
        layout.addWidget(refresh)
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
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.events_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.events_table.setItemDelegateForColumn(3, TechnicalDelegate(self.events_table))
        self.events_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.events_table.cellDoubleClicked.connect(self.open_event)
        layout.addWidget(self.events_table)
        open_button = QPushButton("عرض تقرير الحدث المحدد")
        open_button.clicked.connect(lambda: self.open_event(self.events_table.currentRow(), 0))
        layout.addWidget(open_button)
        self.pages.addWidget(widget)

    def _report(self) -> None:
        widget, layout = page(
            "تفاصيل الحدث والتقرير", "الملاحظة والأدلة والبدائل والبيانات الناقصة والفحص المقترح."
        )
        self.simple_report_text = QTextEdit()
        self.simple_report_text.setReadOnly(True)
        layout.addWidget(self.simple_report_text)
        self.technical_button = QPushButton("عرض التفاصيل الفنية")
        self.technical_button.setCheckable(True)
        layout.addWidget(self.technical_button)
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setPlainText("اختر حدثًا من السجل لعرض تقريره.")
        layout.addWidget(self.report_text)
        self.report_text.hide()
        self.technical_button.toggled.connect(self.report_text.setVisible)
        self.time_plot = TimeSeriesPlot()
        layout.addWidget(self.time_plot)
        self.time_plot.hide()
        self.technical_button.toggled.connect(self.time_plot.setVisible)
        self.pages.addWidget(widget)

    def _settings(self, database: Path) -> None:
        widget, layout = page("الإعدادات", "إعدادات محدودة؛ لا وظائف اتصال مخفية أو غير منفذة.")
        note = QLabel(
            "اللغة: العربية\nالاتجاه: من اليمين إلى اليسار\n"
            "نافذة الحدث: 30 ثانية قبل و30 ثانية بعد، حسب البيانات المتاحة\n"
            "دقة المحاكاة: قراءة كل 200 ms من زمن السيناريو\n"
            "المصدر الافتراضي: محاكاة؛ يبدأ فقط بطلب المستخدم"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
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
        layout.addLayout(settings_form)
        self.language_combo.currentIndexChanged.connect(self.apply_preferences)
        self.theme_combo.currentIndexChanged.connect(self.apply_preferences)
        db = QLineEdit(str(database.resolve()))
        db.setReadOnly(True)
        db.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        layout.addWidget(db)
        layout.addWidget(QLabel("يمكن تغيير ملف التخزين عند التشغيل باستخدام --database"))
        layout.addStretch()
        self.pages.addWidget(widget)

    def on_ready(self) -> None:
        self.backend_ready = True
        self.start_button.setEnabled(True)
        self.set_status("جاهز — لا يوجد اتصال بالمركبة")

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

    def show_sample(self, sample: Sample) -> None:
        self.latest, self.last_received = sample, time.monotonic()
        self.context.setText(
            self.t(
                f"المصدر: {sample.source.value}  •  الحالة: {sample.phase}\n"
                f"زمن الجلسة: {sample.timestamp_ms / 1000:.1f} ثانية  •  "
                f"التسلسل: {sample.sequence_number}"
            )
        )
        for row, spec in enumerate(REGISTRY.all()):
            if spec.kind == "diagnostic":
                value = (
                    ", ".join(sample.dtcs) or self.t("لا رمز مرصود")
                    if sample.dtc_quality == Quality.AVAILABLE
                    else "—"
                )
                status = "معلومات تشخيصية — " + QUALITY_AR[sample.dtc_quality]
            else:
                r = sample.readings.get(spec.sensor_id)
                value = f"{r.value:.1f}" if r and r.value is not None else "—"
                status = QUALITY_AR[r.quality] if r else "مفقودة"
            value_item, status_item = self.sensor_table.item(row, 2), self.sensor_table.item(row, 4)
            assert value_item is not None and status_item is not None
            value_item.setText(ltr(value))
            status_item.setText(self.t(status))
            name_item = self.sensor_table.item(row, 0)
            assert name_item is not None
            name_item.setText(self.t(spec.arabic_name))
            if spec.sensor_id in self.cards:
                self.cards[spec.sensor_id].setText(
                    self.t(f"{spec.arabic_name}\n{ltr(value + ' ' + spec.unit)}\n{status}")
                )

    def update_age(self) -> None:
        if self.latest:
            seconds = time.monotonic() - self.last_received
            state = "قديمة — ليست قراءة حية" if seconds > 3 else "آخر بيانات مستلمة"
            self.age.setText(
                self.t(f"{state} • منذ {seconds:.1f} ثانية • {self.latest.source.value}")
            )

    def show_events(self, rows: list[dict[str, Any]]) -> None:
        self.event_rows = rows
        selected = self.events_table.currentRow()
        self.events_table.setRowCount(len(rows))
        for row, data in enumerate(rows):
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
            for column, text in enumerate(texts):
                item = QTableWidgetItem(self.t(text))
                item.setToolTip(self.t(text))
                if column == len(texts) - 1:  # detection method: tooltip states the AI result
                    item.setToolTip(
                        self.t(text)
                        + "\n"
                        + ai.message(data.get("ai_state", ai.NOT_RECORDED), self.language)
                    )
                self.events_table.setItem(row, column, item)
            self.events_table.setRowHeight(row, 60 if data["kind"] in RULES else 30)
        if 0 <= selected < len(rows):
            self.events_table.selectRow(selected)

    def open_event(self, row: int, column: int) -> None:
        item = self.events_table.item(row, 3) if row >= 0 else None
        if item is not None:
            self.worker.submit("report", event_id=item.text(), language=self.language)

    def show_report(self, text: str) -> None:
        self.report_text.setPlainText(text)
        self.navigation.setCurrentRow(4)

    def show_ai(self, result: dict[str, Any]) -> None:
        decision = result.get("decision", "UNAVAILABLE")
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

    def show_error(self, message: str) -> None:
        self.error_message = message
        if self.source_combo.isEnabled():
            self.verify_button.setEnabled(True)
        self.error_label.setText(self.t(message))
        self.error_label.show()

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
        visible = {
            self.host_input: kind == "network",
            self.network_port: kind == "network",
            self.mode_combo: sim,
            self.family_combo: sim,
            self.scenario_combo: sim and mode == "LEGACY",
            self.fault_list: sim and mode == "FAULT_INJECTION" and not multi,
            self.multisensor_list: sim and mode == "FAULT_INJECTION" and multi,
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
        self.preferences.sync()
        return args

    def verify_source(self) -> None:
        try:
            self.verify_button.setEnabled(False)
            self.connection_details.setText(self.t("CONNECTING"))
            self.worker.submit("verify", **self.source_arguments())
        except ValueError as exc:
            self.verify_button.setEnabled(True)
            self.show_error(str(exc))

    def show_ports(self, ports: list[str]) -> None:
        current = self.port_input.text()
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        self.port_combo.setCurrentText(current or (ports[0] if ports else ""))
        self.connection_details.setText(self.t("PORT_AVAILABLE" if ports else "DISCONNECTED"))

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

    def show_device(self, info: dict[str, Any]) -> None:
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
        self.ai_enabled.setEnabled(not running)
        self.start_button.setEnabled(not running and self.backend_ready)
        self.source_combo.setEnabled(not running)
        self.verify_button.setEnabled(not running)
        for row in range(1, self.source_form.rowCount()):
            item = self.source_form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            control = item.widget() if item else None
            if control:
                control.setEnabled(not running)
        if running:
            self.simulation_summary.clear()

    def _capture_texts(self) -> None:
        self.static_texts: list[tuple[Any, str]] = []
        for control in self.findChildren(QLabel) + self.findChildren(QPushButton):
            if control not in (self.status_label, self.error_label):
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

    def apply_preferences(self) -> None:
        self.language = str(self.language_combo.currentData())
        self.theme = str(self.theme_combo.currentData())
        self.preferences.setValue("language", self.language)
        self.preferences.setValue("theme", self.theme)
        self.preferences.sync()
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if self.language == "ar"
            else Qt.LayoutDirection.LeftToRight
        )
        self.report_text.setLayoutDirection(self.layoutDirection())
        self.simple_report_text.setLayoutDirection(self.layoutDirection())
        self.ai_enabled.setText(
            "تفعيل مراقبة AI التجريبية"
            if self.language == "ar"
            else "Enable experimental AI monitoring"
        )
        self.setWindowTitle(self.t("DoctorCAR | المراقبة والتسجيل التجريبي"))
        style = STYLE + "\nQListWidget#faultList { color: #173042; background: white; }"
        if self.theme == "dark":
            for old, new in {
                "#173042": "#e6edf3",
                "#f4f7f8": "#16232e",
                "background: white": "background: #213342",
                "#dbe5e9": "#435b6b",
                "#cbdade": "#435b6b",
                "#edf2f4": "#354b5c",
                "#e7eff1": "#2b4354",
                "#d9efed": "#285c66",
                "#fff2d8": "#473c28",
                "#715018": "#ffe0a6",
                "#fff0ef": "#492b35",
                "#a22b35": "#ffb1b8",
                "#087f79": "#126f6b",
            }.items():
                style = style.replace(old, new)
        self.setStyleSheet(style)
        for control, original in self.static_texts:
            control.setText(self.t(original))
        self.set_status(getattr(self, "status_text", "تهيئة التخزين المحلي…"))
        if hasattr(self, "error_message"):
            self.error_label.setText(self.t(self.error_message))
        if self.latest is not None:  # DEF-011: re-render language-dependent cells (DTC, status)
            received = self.last_received
            self.show_sample(self.latest)
            self.last_received = received
        for combo, originals in self.combo_texts:
            for i, original in enumerate(originals):
                combo.setItemText(i, self.t(original))
        for i, original in enumerate(self.nav_texts):
            self.navigation.item(i).setText(self.t(original))
        for table, originals in self.headers:
            table.setHorizontalHeaderLabels([self.t(x) for x in originals])
        for control, original in self.placeholder_texts:
            control.setPlaceholderText(self.t(original))
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
        for row, spec in enumerate(REGISTRY.all()):
            item = self.sensor_table.item(row, 0)
            assert item is not None
            item.setText(self.t(spec.arabic_name))
            if not self.latest:
                status_item = self.sensor_table.item(row, 4)
                assert status_item is not None
                status_item.setText(self.t("لم تصل بيانات"))
        if self.report_text.toPlainText() in (
            "اختر حدثًا من السجل لعرض تقريره.",
            "Select an event from history to view its report.",
        ):
            self.report_text.setPlainText(self.t("اختر حدثًا من السجل لعرض تقريره."))
        if self.latest:
            received = self.last_received
            self.show_sample(self.latest)
            self.last_received = received
            self.update_age()
        self.show_events(self.event_rows)
        if self.events_table.currentRow() >= 0:
            self.open_event(self.events_table.currentRow(), 0)

    def set_status(self, message: str) -> None:
        self.status_text = message
        self.status_label.setText(self.t(message))
