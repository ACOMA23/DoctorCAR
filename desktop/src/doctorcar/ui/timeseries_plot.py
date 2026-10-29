"""Small Qt-only technical plot; missing readings break lines instead of becoming zero."""

from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from doctorcar.core.sensor_registry import REGISTRY
from doctorcar.diagnostics.human_report import NAMES
from doctorcar.ui.theme import palette


class SeriesCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.points: list[list[Any]] = []
        self.unit = ""
        self.theme = "light"
        self.setMinimumHeight(170)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        colors = palette(self.theme)
        painter.fillRect(self.rect(), QColor(colors.surface))
        painter.setPen(QColor(colors.text))
        good = [(t, v) for t, v in self.points if v is not None]
        if len(good) < 2:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "—")
            return
        low, high = min(v for _, v in good), max(v for _, v in good)
        start, end = self.points[0][0], self.points[-1][0]
        painter.drawText(
            10,
            20,
            f"{low:.1f} .. {high:.1f} {self.unit} | {start / 1000:.1f} .. {end / 1000:.1f} s",
        )
        painter.setPen(QPen(QColor(colors.primary), 2))
        previous = None
        for t, v in self.points:
            if v is None:
                previous = None
                continue
            point = QPointF(
                15 + (self.width() - 30) * (t - start) / max(1, end - start),
                self.height() - 15 - (self.height() - 50) * (v - low) / max(1e-9, high - low),
            )
            if previous is not None:
                painter.drawLine(previous, point)
            previous = point


class TimeSeriesPlot(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.selector = QComboBox()
        self.canvas = SeriesCanvas()
        layout.addWidget(self.selector)
        layout.addWidget(self.canvas)
        self.series: dict[str, Any] = {}
        self.selector.currentIndexChanged.connect(self.select)

    def set_theme(self, theme: str) -> None:
        self.canvas.theme = theme
        self.canvas.update()

    def set_series(self, data: dict[str, Any], language: str = "ar") -> None:
        self.series = data
        self.selector.clear()
        for sensor in data:
            self.selector.addItem(
                REGISTRY.get(sensor).arabic_name if language == "ar" else NAMES[sensor], sensor
            )
        self.select()

    def select(self) -> None:
        sensor = self.selector.currentData()
        self.canvas.points = self.series.get(sensor, [])
        self.canvas.unit = REGISTRY.get(sensor).unit if sensor else ""
        self.canvas.update()
