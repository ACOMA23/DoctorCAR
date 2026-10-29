"""Reusable presentation widgets of the design system. They only display data they are given."""

from __future__ import annotations

import ctypes
import re
import sys
import time
from collections import deque
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QBoxLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from doctorcar.ui.theme import DARK, Palette, palette, tone_colors


class Motion:
    """Global motion switch: animations run only when enabled (setting and OS animation preference)."""

    user_enabled = True

    @classmethod
    def os_allows(cls) -> bool:
        if sys.platform != "win32":
            return True
        flag = ctypes.c_int(1)
        try:
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)
        except Exception:
            return True
        return bool(flag.value)

    @classmethod
    def enabled(cls) -> bool:
        return cls.user_enabled and cls.os_allows()


def clear_effect(widget: QWidget) -> None:
    widget.setGraphicsEffect(None)  # type: ignore[arg-type]


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_property(widget: QWidget, name: str, value: Any) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, variant: str = "", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if variant:
        widget.setProperty("variant", variant)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def card(spacing: int = 12, margins: int = 16) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    return frame, layout


# ----------------------------------------------------------------------------- icons
def _stroke(painter: QPainter, color: QColor, width: float = 1.8) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def make_icon(name: str, color: str, size: int = 22) -> QIcon:
    """Vector line icons drawn in code (no external assets, crisp at any DPI)."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size * scale / 24.0, size * scale / 24.0)
    _stroke(p, QColor(color))
    path = QPainterPath()
    if name == "dashboard":
        for x, y, w, h in ((3, 3, 8, 8), (13, 3, 8, 5), (13, 10, 8, 11), (3, 13, 8, 8)):
            p.drawRoundedRect(QRectF(x, y, w, h), 2, 2)
    elif name == "connection":
        p.drawEllipse(QPointF(12, 12), 2.2, 2.2)
        p.drawArc(QRectF(6, 6, 12, 12), 40 * 16, 100 * 16)
        p.drawArc(QRectF(6, 6, 12, 12), 220 * 16, 100 * 16)
        p.drawArc(QRectF(2.5, 2.5, 19, 19), 45 * 16, 90 * 16)
        p.drawArc(QRectF(2.5, 2.5, 19, 19), 225 * 16, 90 * 16)
    elif name == "sensors":
        p.drawArc(QRectF(3, 5, 18, 18), 0, 180 * 16)
        p.drawLine(QPointF(12, 14), QPointF(17, 8))
        p.drawLine(QPointF(4, 17), QPointF(20, 17))
    elif name == "events":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        p.drawLine(QPointF(12, 7), QPointF(12, 12))
        p.drawLine(QPointF(12, 12), QPointF(15.5, 14))
    elif name == "report":
        path.addRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
        p.drawPath(path)
        for y in (9, 13, 17):
            p.drawLine(QPointF(8.5, y), QPointF(15.5, y))
    elif name == "settings":
        for y, x in ((7, 9), (12, 15), (17, 8)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "play":
        path.moveTo(8, 5)
        path.lineTo(19, 12)
        path.lineTo(8, 19)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "stop":
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif name == "collapse":
        p.drawLine(QPointF(9, 6), QPointF(15, 12))
        p.drawLine(QPointF(15, 12), QPointF(9, 18))
    elif name == "search":
        p.drawEllipse(QPointF(11, 11), 6, 6)
        p.drawLine(QPointF(15.5, 15.5), QPointF(20, 20))
    elif name == "inbox":
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 3, 3)
        p.drawLine(QPointF(3, 13), QPointF(8.5, 13))
        p.drawLine(QPointF(15.5, 13), QPointF(21, 13))
        p.drawArc(QRectF(8.5, 10, 7, 6), 180 * 16, 180 * 16)
    elif name == "warning":
        path.moveTo(12, 4)
        path.lineTo(21, 20)
        path.lineTo(3, 20)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(12, 10), QPointF(12, 14.5))
        p.drawPoint(QPointF(12, 17.3))
    else:  # generic dot
        p.drawEllipse(QPointF(12, 12), 4, 4)
    p.end()
    return QIcon(pixmap)


# ----------------------------------------------------------------------------- status
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9 ._:/-]*[A-Za-z0-9:]|[A-Za-z]")
ARABIC_CHARS = re.compile(r"[\u0600-\u06FF]")


def bidi_safe(text: str) -> str:
    """Isolate Latin runs inside Arabic text so punctuation and order stay correct in RTL."""
    if not ARABIC_CHARS.search(text):
        return text
    return LATIN_RUN.sub(lambda m: "\u2066" + m.group(0) + "\u2069", text)


TONE_SYMBOL = {"ok": "✓", "warn": "▲", "danger": "✕", "info": "●", "idle": "○"}


class ElidedLabel(QLabel):
    """Single-line label that elides with an ellipsis instead of being cut; the full text is the tooltip."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = text
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        self._full = text
        self.setToolTip(text)
        self._apply()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event: Any) -> None:
        self._apply()
        super().resizeEvent(event)

    def _apply(self) -> None:
        width = max(self.width() - 2, 40)
        super().setText(
            self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width)
        )


class StatusPill(QLabel):
    """Status badge. The symbol (not only the colour) carries the meaning."""

    def __init__(self, text: str = "", tone: str = "idle") -> None:
        super().__init__()
        self.setObjectName("pill")
        self.tone = ""
        self.set_state(text, tone)

    def set_state(self, text: str, tone: str, tooltip: str = "") -> None:
        self.setText(f"{TONE_SYMBOL.get(tone, '○')}  {bidi_safe(text)}")
        self.setToolTip(tooltip or text)
        self.setAccessibleName(text)
        if tone != self.tone:
            self.tone = tone
            set_property(self, "tone", tone)


class EmptyState(QWidget):
    """Icon + title + hint (+ optional real action) shown instead of an empty table or page."""

    def __init__(self, icon: str, title: str, hint: str, action_text: str = "") -> None:
        super().__init__()
        self.icon_name = icon
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = label(title, "subtitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = label(hint, "muted", wrap=True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.action = button(action_text, "primary") if action_text else None
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        if self.action:
            layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignCenter)
        self.apply_theme("light")

    def apply_theme(self, theme: str) -> None:
        self.icon_label.setPixmap(
            make_icon(self.icon_name, palette(theme).muted, 48).pixmap(48, 48)
        )

    def set_texts(self, title: str, hint: str, action: str = "") -> None:
        self.title.setText(title)
        self.hint.setText(hint)
        if self.action and action:
            self.action.setText(action)


# ----------------------------------------------------------------------------- live values
class Sparkline(QWidget):
    """Last N trusted values of one sensor. Gaps (missing/invalid/stale) break the line; nothing is invented."""

    def __init__(self, capacity: int = 90) -> None:
        super().__init__()
        self.points: deque[float | None] = deque(maxlen=capacity)
        self.color = "#2BC8DB"
        self.setFixedHeight(34)
        self.setMinimumWidth(80)
        self.setAccessibleName("trend")

    def push(self, value: float | None) -> None:
        self.points.append(value)

    def clear(self) -> None:
        self.points.clear()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        values = [v for v in self.points if v is not None]
        if len(values) < 2:
            return
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(self.color), 1.6))
        w, h, n = self.width() - 4, self.height() - 6, max(self.points.maxlen or 1, 2) - 1
        path = QPainterPath()
        drawing = False
        offset = (self.points.maxlen or len(self.points)) - len(self.points)
        for i, v in enumerate(self.points):
            if v is None:
                drawing = False
                continue
            x = 2 + (i + offset) * w / n
            y = 3 + (hi - v) * h / span
            if drawing:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                drawing = True
        painter.drawPath(path)


class MetricTile(QFrame):
    """One sensor reading: name, value, unit, quality, age and trend.

    The quality text and symbol (not the colour alone) say whether the reading is available, stale,
    missing, invalid or unsupported. A flash highlights a large change that came from a real new sample.
    """

    QUALITY_TONE = {
        "AVAILABLE": "ok",
        "STALE": "warn",
        "MISSING": "danger",
        "INVALID": "danger",
        "UNSUPPORTED": "idle",
        "NONE": "idle",
    }

    def __init__(self, sensor_id: str, name: str, unit: str, spark: bool = True) -> None:
        super().__init__()
        self.sensor_id = sensor_id
        self.setProperty("card", True)
        self.setMinimumWidth(190)
        self.last_value: float | None = None
        self.quality_key = "NONE"
        self._flash = 0.0
        self._flash_color = QColor("#2BC8DB")
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.55)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(520)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_flash)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        self.name_label = label(name, "muted", wrap=True)
        self.id_label = ElidedLabel(sensor_id)
        self.id_label.setProperty("role", "caption")
        self.id_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        lay.addWidget(self.name_label)
        lay.addWidget(self.id_label)
        row = QHBoxLayout()
        row.setDirection(QBoxLayout.Direction.LeftToRight)
        self.value_label = label("—", "metric")
        self.value_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.unit_label = label(unit, "muted")
        self.unit_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row.addWidget(self.value_label)
        row.addWidget(self.unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        lay.addLayout(row)
        self.spark = Sparkline() if spark else None
        if self.spark:
            lay.addWidget(self.spark)
        foot = QHBoxLayout()
        self.quality = StatusPill("—", "idle")
        self.quality.setMinimumWidth(0)
        self.age_label = label("", "caption")
        foot.addWidget(self.quality)
        foot.addStretch(1)
        foot.addWidget(self.age_label)
        lay.addLayout(foot)
        self.setAccessibleName(name)

    def _on_flash(self, value: Any) -> None:
        self._flash = float(value)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._flash > 0.01:
            painter = QPainter(self)
            color = QColor(self._flash_color)
            color.setAlphaF(self._flash * 0.35)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 15, 15)

    def set_reading(
        self,
        value_text: str,
        quality_key: str,
        quality_text: str,
        age_text: str,
        numeric: float | None,
        threshold: float,
        stale: bool,
        theme: str,
        new_sample: bool,
    ) -> None:
        """Show a reading. ``new_sample`` is False when only the age/staleness is refreshed."""
        self.value_label.setText(value_text)
        text_value = numeric is None and value_text.strip("\u2066\u2069 ") not in ("—", "")
        set_property(self.value_label, "role", "subtitle" if text_value else "metric")
        self.quality.set_state(quality_text, self.QUALITY_TONE.get(quality_key, "idle"))
        self.age_label.setText(age_text)
        set_property(self, "state", "stale" if stale else "active")
        if not new_sample:
            return
        if self.spark:
            self.spark.color = palette(theme).primary
            self.spark.push(numeric if quality_key == "AVAILABLE" else None)
            self.spark.update()
        if (
            numeric is not None
            and quality_key == "AVAILABLE"
            and self.last_value is not None
            and abs(numeric - self.last_value) >= threshold
            and Motion.enabled()
        ):
            self._flash_color = QColor(palette(theme).primary)
            self._anim.stop()
            self._anim.start()
        self.last_value = numeric if quality_key == "AVAILABLE" else None

    def reset(self, unit: str) -> None:
        self.last_value = None
        self.value_label.setText("—")
        self.unit_label.setText(unit)
        if self.spark:
            self.spark.clear()


# ----------------------------------------------------------------------------- notifications
class Toast(QFrame):
    def __init__(self, kind: str, text: str, theme: str, sticky: bool) -> None:
        super().__init__()
        self.setObjectName("toast")
        self.kind, self.text, self.count = kind, text, 1
        tone = {"success": "ok", "info": "info", "warning": "warn", "error": "danger"}[kind]
        fg, bg = tone_colors(theme, tone)
        self.setStyleSheet(
            f"QFrame#toast {{ background: {bg}; border: 1px solid {fg}; border-radius: 12px; }}"
            f"QLabel {{ color: {fg}; background: transparent; }}"
            f"QPushButton {{ background: transparent; color: {fg}; border: none; padding: 2px 8px; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 8, 10)
        self.symbol = QLabel(TONE_SYMBOL[tone])
        self.body = QLabel(text)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.badge = QLabel("")
        close = QPushButton("✕")
        close.setAccessibleName("close")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        lay.addWidget(self.symbol)
        lay.addWidget(self.body, 1)
        lay.addWidget(self.badge)
        lay.addWidget(close)
        self.setAccessibleName(f"{kind}: {text}")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        if not sticky:
            self.timer.start({"success": 3500, "info": 4500, "warning": 8000}.get(kind, 8000))

    def bump(self) -> None:
        self.count += 1
        self.badge.setText(f"×{self.count}")
        if self.timer.interval() > 0:
            self.timer.start()

    def dismiss(self) -> None:
        host = self.parent()
        if isinstance(host, ToastHost):
            host.remove(self)


class ToastHost(QWidget):
    """Overlay that stacks toasts at the top of the window. Identical messages are merged, not repeated."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setObjectName("toastHost")
        self.setStyleSheet("QWidget#toastHost { background: transparent; }")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.toasts: list[Toast] = []
        self.theme = "light"
        self.hide()

    def push(self, kind: str, text: str, sticky: bool = False) -> Toast:
        for existing in self.toasts:
            if existing.kind == kind and existing.text == text:
                existing.bump()
                return existing
        toast = Toast(kind, text, self.theme, sticky or kind == "error")
        toast.setParent(self)
        self.lay.addWidget(toast)
        self.toasts.append(toast)
        toast.show()
        if Motion.enabled():
            effect = QGraphicsOpacityEffect(toast)
            toast.setGraphicsEffect(effect)
            anim = QVariantAnimation(toast)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.valueChanged.connect(lambda v: effect.setOpacity(float(v)))
            anim.finished.connect(lambda: clear_effect(toast))
            anim.start()
        self.reposition()
        return toast

    def remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
            self.lay.removeWidget(toast)
            toast.hide()
            toast.deleteLater()
        self.reposition()

    def clear(self) -> None:
        for toast in list(self.toasts):
            self.remove(toast)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        if not self.toasts:
            self.hide()
            return
        width = min(460, max(280, parent.width() - 48))
        self.setFixedWidth(width)
        self.setFixedHeight(self.lay.sizeHint().height())
        left = (
            24
            if parent.layoutDirection() == Qt.LayoutDirection.RightToLeft
            else parent.width() - width - 24
        )
        self.move(QPoint(left, max(60, parent.height() - self.height() - 52)))
        self.show()
        self.raise_()


# ----------------------------------------------------------------------------- navigation
class NavDelegate(QStyledItemDelegate):
    """Sidebar row: icon + label, active indicator bar, collapsed (icon-only) mode."""

    def __init__(self, parent: QWidget, theme: str = "light") -> None:
        super().__init__(parent)
        self.theme = theme
        self.collapsed = False
        self.icons: dict[str, QIcon] = {}
        self.icons_active: dict[str, QIcon] = {}

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(option.rect.width(), 46)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        p: Palette = palette(self.theme)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 3, -4, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setBrush(QColor(p.sidebar_active))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            bar = QRectF(
                rect.right() - 4
                if option.direction == Qt.LayoutDirection.RightToLeft
                else rect.left(),
                rect.top() + 10,
                4,
                rect.height() - 20,
            )
            painter.setBrush(QColor(DARK.primary))
            painter.drawRoundedRect(bar, 2, 2)
        elif hovered:
            hover = QColor(p.sidebar_active)
            hover.setAlpha(110)
            painter.setBrush(hover)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
        if option.state & QStyle.StateFlag.State_HasFocus and selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(DARK.focus), 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)
        row = index.row()
        color = p.sidebar_text if selected else p.sidebar_muted
        icon = (self.icons_active if selected else self.icons).get(str(row))
        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        icon_rect = QRect(0, 0, 22, 22)
        if self.collapsed:
            icon_rect.moveCenter(option.rect.center())
        else:
            x = option.rect.right() - 16 - 22 if rtl else option.rect.left() + 16
            icon_rect.moveTo(x, option.rect.center().y() - 11)
        if icon is not None:
            painter.drawPixmap(icon_rect, icon.pixmap(22, 22))
        if not self.collapsed:
            painter.setPen(QColor(color))
            font = painter.font()
            font.setBold(selected)
            painter.setFont(font)
            text_rect = option.rect.adjusted(14, 0, -(16 + 22 + 12) if rtl else -10, 0)
            if not rtl:
                text_rect = option.rect.adjusted(16 + 22 + 12, 0, -10, 0)
            align = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
            )
            painter.drawText(
                text_rect,
                int(align),
                painter.fontMetrics().elidedText(
                    str(index.data(Qt.ItemDataRole.DisplayRole)),
                    Qt.TextElideMode.ElideRight,
                    text_rect.width(),
                ),
            )
        painter.restore()


def fade_in(widget: QWidget, duration: int = 140) -> None:
    """Short opacity transition for a page that just became visible (skipped when motion is off)."""
    if not Motion.enabled() or not widget.isVisible():
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(lambda v: effect.setOpacity(float(v)))
    anim.finished.connect(lambda: clear_effect(widget))
    anim.start()


def humanize_age(seconds: float) -> str:
    if seconds < 1:
        return "الآن"
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.0f}m"


def monotonic_ms() -> float:
    return time.monotonic() * 1000


class AdaptiveGrid(QWidget):
    """Grid that re-flows its (already created) widgets to the available width; no widget is rebuilt."""

    def __init__(self, min_width: int = 210, spacing: int = 12) -> None:
        super().__init__()
        from PySide6.QtWidgets import QGridLayout

        self.min_width = min_width
        self.items: list[QWidget] = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        self.columns = 0

    def set_items(self, items: list[QWidget]) -> None:
        self.items = items
        for item in items:
            item.setParent(self)
        self.columns = 0
        self.reflow()

    def cell_width(self) -> int:
        """Column width: the configured minimum, or the widest button text (buttons are never cut)."""
        wide = [
            i.sizeHint().width()
            for i in self.items
            if isinstance(i, QAbstractButton) and not i.isHidden()
        ]
        return max([self.min_width, *wide])

    def reflow(self) -> None:
        visible = [i for i in self.items if not i.isHidden()]
        cols = max(
            1, min(len(visible) or 1, self.width() // self.cell_width() if self.width() else 3)
        )
        for item in self.items:
            self.grid.removeWidget(item)
        for n, item in enumerate(visible):
            self.grid.addWidget(item, n // cols, n % cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        for c in range(cols, max(self.columns, cols) + 1):
            self.grid.setColumnStretch(c, 0)
        self.columns = cols

    def minimumSizeHint(self) -> QSize:
        """One column is always enough: the grid reflows instead of forcing the page wider."""
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.min_width + 24), hint.height())

    def resizeEvent(self, event: Any) -> None:
        visible = len([i for i in self.items if not i.isHidden()])
        cols = max(1, min(max(visible, 1), self.width() // self.cell_width()))
        if cols != self.columns:
            self.reflow()
        super().resizeEvent(event)


class EventTimeline(QWidget):
    """T-30 s / detection / T+30 s bar drawn from the recorded window only.

    ``first_ms``/``last_ms`` are the first and last stored samples. If either side has less than the
    nominal 30 s, the missing part is drawn as an empty (hatched) segment and the status is stated.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(86)
        self.trigger_ms: float | None = None
        self.first_ms: float | None = None
        self.last_ms: float | None = None
        self.status = ""
        self.theme = "light"
        self.texts = ("-30 s", "T", "+30 s")
        self.setAccessibleName("event timeline")

    def set_window(
        self, trigger_ms: float | None, first_ms: float | None, last_ms: float | None, status: str
    ) -> None:
        self.trigger_ms, self.first_ms, self.last_ms, self.status = (
            trigger_ms,
            first_ms,
            last_ms,
            status,
        )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.trigger_ms is None or self.first_ms is None or self.last_ms is None:
            return
        p = palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, y, h = 24.0, self.width() - 24.0, 34.0, 14.0
        span = right - left
        t0, t1 = self.trigger_ms - 30000, self.trigger_ms + 30000

        def x_of(ms: float) -> float:
            return left + (ms - t0) / (t1 - t0) * span

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.surface_alt))
        painter.drawRoundedRect(QRectF(left, y, span, h), 7, 7)
        a, b = max(self.first_ms, t0), min(self.last_ms, t1)
        if b > a:
            xt = x_of(self.trigger_ms)
            painter.setBrush(QColor(p.info))
            painter.drawRect(QRectF(x_of(a), y, max(xt - x_of(a), 0), h))
            painter.setBrush(QColor(p.primary))
            painter.drawRect(QRectF(xt, y, max(x_of(b) - xt, 0), h))
        painter.setBrush(QColor(p.text))
        xt = x_of(self.trigger_ms)
        painter.drawRect(QRectF(xt - 1.5, y - 8, 3, h + 16))
        painter.setPen(QColor(p.muted))
        small = painter.font()
        small.setPointSize(8)
        painter.setFont(small)
        painter.drawText(
            QRectF(left - 10, y + h + 6, 90, 16),
            int(Qt.AlignmentFlag.AlignLeft),
            f"{(self.first_ms - self.trigger_ms) / 1000:+.1f} s",
        )
        painter.drawText(
            QRectF(right - 80, y + h + 6, 90, 16),
            int(Qt.AlignmentFlag.AlignRight),
            f"{(self.last_ms - self.trigger_ms) / 1000:+.1f} s",
        )
        painter.setPen(QColor(p.text))
        painter.drawText(
            QRectF(xt - 50, y - 24, 100, 16),
            int(Qt.AlignmentFlag.AlignCenter),
            f"T = {self.trigger_ms / 1000:.1f} s",
        )
