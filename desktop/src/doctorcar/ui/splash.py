"""Startup splash window. It shows the real startup stages and an indeterminate activity bar.

Progress is never fabricated: the bar is indeterminate and each stage line flips to done or failed
only when the corresponding real operation reports back.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QApplication, QWidget

from doctorcar.ui.theme import app_font, palette

TEXTS = {
    "ar": {
        "tagline": "Smart Vehicle Diagnostics",
        "sub": "تشخيص ذكي للمركبات — نموذج أولي للمحاكاة والاختبار",
        "failed": "تعذر إكمال بدء التشغيل",
    },
    "en": {
        "tagline": "Smart Vehicle Diagnostics",
        "sub": "Prototype for simulation and testing — not a vehicle diagnosis",
        "failed": "Startup could not complete",
    },
}


class SplashWindow(QWidget):
    """Frameless centred window. Stage state is one of: pending, running, done, failed."""

    dismissed = Signal()

    def __init__(self, theme: str = "dark", language: str = "ar") -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.theme, self.language = theme, language
        self.stages: list[tuple[str, str, str]] = []  # key, text, state
        self.note = ""
        self.failure = ""
        self.phase = 0.0
        self.setFixedSize(580, 380)
        self.setFont(app_font())
        self.setWindowTitle("DoctorCAR")
        self.setAccessibleName("DoctorCAR startup")
        self.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if language == "ar" else Qt.LayoutDirection.LeftToRight
        )
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    # --- stage API -----------------------------------------------------------------------
    def add_stage(self, key: str, text: str) -> None:
        self.stages.append((key, text, "pending"))
        self.update()

    def set_state(self, key: str, state: str) -> None:
        self.stages = [(k, t, state if k == key else s) for k, t, s in self.stages]
        self.update()

    def start_stage(self, key: str) -> None:
        self.set_state(key, "running")

    def finish_stage(self, key: str, ok: bool = True) -> None:
        self.set_state(key, "done" if ok else "failed")

    def state_of(self, key: str) -> str:
        return next((s for k, _, s in self.stages if k == key), "")

    def show_failure(self, message: str) -> None:
        self.failure = message
        self.timer.stop()
        self.update()

    def set_note(self, text: str) -> None:
        self.note = text
        self.update()

    # --- animation --------------------------------------------------------------------
    def _tick(self) -> None:
        self.phase = (self.phase + 0.018) % 1.0
        self.update(QRectF(40, 300, 500, 8).toAlignedRect())

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self.timer.stop()
        self.dismissed.emit()
        super().closeEvent(event)  # type: ignore[arg-type]

    # --- painting ---------------------------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:
        p = palette(self.theme)
        t = TEXTS.get(self.language, TEXTS["en"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(p.surface_alt if self.theme == "light" else p.surface))
        gradient.setColorAt(1.0, QColor(p.bg))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(p.border), 1))
        painter.drawRoundedRect(rect, 18, 18)
        # logo mark: gauge arc with a needle
        cx, cy = self.width() / 2, 92
        painter.setPen(QPen(QColor(p.primary), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(cx - 34, cy - 34, 68, 68), 210 * 16, -240 * 16)
        painter.setPen(QPen(QColor(p.text), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, cy), QPointF(cx + 17, cy - 19))
        painter.setBrush(QColor(p.primary))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 5, 5)
        # title block
        title_font = QFont(self.font())
        title_font.setPointSize(26)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(p.text))
        painter.drawText(
            QRectF(0, 134, self.width(), 44), int(Qt.AlignmentFlag.AlignCenter), "DoctorCAR"
        )
        sub_font = QFont(self.font())
        sub_font.setPointSize(11)
        painter.setFont(sub_font)
        painter.setPen(QColor(p.primary))
        painter.drawText(
            QRectF(0, 178, self.width(), 24), int(Qt.AlignmentFlag.AlignCenter), t["tagline"]
        )
        small = QFont(self.font())
        small.setPointSize(9)
        painter.setFont(small)
        painter.setPen(QColor(p.muted))
        painter.drawText(
            QRectF(20, 202, self.width() - 40, 22), int(Qt.AlignmentFlag.AlignCenter), t["sub"]
        )
        # stages (only real ones)
        y = 232
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        cols = 2
        per_col = (len(self.stages) + cols - 1) // cols
        for i, (_, text, state) in enumerate(self.stages):
            col, row = divmod(i, per_col)
            x = self.width() - 40 - col * 250 if rtl else 40 + col * 250
            glyph, color = {
                "pending": ("○", p.muted),
                "running": ("◌", p.primary),
                "done": ("✓", p.success),
                "failed": ("✕", p.danger),
            }[state]
            painter.setPen(QColor(color))
            line = f"{glyph}  {text}"
            box = (
                QRectF(x - 230, y + row * 20, 230, 20) if rtl else QRectF(x, y + row * 20, 230, 20)
            )
            painter.drawText(
                box,
                int(
                    (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)
                    | Qt.AlignmentFlag.AlignVCenter
                ),
                line,
            )
        # indeterminate bar
        track = QRectF(40, 304, self.width() - 80, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.surface_alt if self.theme == "dark" else p.border))
        painter.drawRoundedRect(track, 3, 3)
        if self.failure:
            painter.setBrush(QColor(p.danger))
            painter.drawRoundedRect(track, 3, 3)
            painter.setFont(small)
            painter.setPen(QColor(p.danger))
            painter.drawText(
                QRectF(30, 320, self.width() - 60, 50),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                f"{t['failed']}: {self.failure}",
            )
        else:
            chunk = track.width() * 0.28
            x0 = track.left() - chunk + (track.width() + chunk) * self.phase
            clip = QRectF(
                max(x0, track.left()),
                track.top(),
                min(chunk, track.right() - max(x0, track.left()), x0 + chunk - track.left()),
                track.height(),
            )
            if clip.width() > 0:
                painter.setBrush(QColor(p.primary))
                painter.drawRoundedRect(clip, 3, 3)
            running = next((text for _, text, s in self.stages if s == "running"), "")
            painter.setFont(small)
            painter.setPen(QColor(p.muted))
            painter.drawText(
                QRectF(30, 322, self.width() - 60, 24),
                int(Qt.AlignmentFlag.AlignCenter),
                self.note or running,
            )
