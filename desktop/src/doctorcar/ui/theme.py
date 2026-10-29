"""Design system: tokens, typography, spacing and the single application stylesheet.

Every colour, size and radius used by the UI comes from here. Widgets select their look through
Qt dynamic properties (``role``, ``variant``, ``tone``) so no other module needs its own QSS.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPixmap

# Fonts shipped with Windows are used as a fallback chain; nothing is bundled or downloaded.
# Segoe UI / Tahoma / Arial all cover Arabic and Latin glyphs. The first installed family wins.
FONT_STACK: Final = ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "Arial")
MONO_STACK: Final = ("Cascadia Mono", "Consolas", "Courier New")

SPACE: Final = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS: Final = {"sm": 8, "md": 12, "lg": 16}
# Point sizes of the type scale (hierarchy is fixed; pages never invent their own sizes).
TYPE: Final = {"caption": 9, "body": 10, "label": 10, "subtitle": 12, "title": 17, "display": 24}


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    sidebar: str
    sidebar_text: str
    sidebar_muted: str
    sidebar_active: str
    border: str
    text: str
    muted: str
    primary: str
    primary_hover: str
    primary_text: str
    success: str
    warning: str
    danger: str
    info: str
    success_bg: str
    warning_bg: str
    danger_bg: str
    info_bg: str
    focus: str
    selection: str


DARK: Final = Palette(
    bg="#0B1622",
    surface="#122232",
    surface_alt="#183044",
    sidebar="#08121C",
    sidebar_text="#E6EEF5",
    sidebar_muted="#8CA3B5",
    sidebar_active="#143A4C",
    border="#26405A",
    text="#E6EEF5",
    muted="#9BB0C1",
    primary="#2BC8DB",
    primary_hover="#5AD8E7",
    primary_text="#04212A",
    success="#4BE09B",
    warning="#F6BB55",
    danger="#FF7B7B",
    info="#6EB6FF",
    success_bg="#0F3427",
    warning_bg="#3B2D12",
    danger_bg="#3E1C22",
    info_bg="#13304D",
    focus="#8FE8F2",
    selection="#1D4B5E",
)
LIGHT: Final = Palette(
    bg="#F1F5F8",
    surface="#FFFFFF",
    surface_alt="#E8EFF4",
    sidebar="#0F2A3A",
    sidebar_text="#EAF3F7",
    sidebar_muted="#A9C1CE",
    sidebar_active="#1B4B5F",
    border="#CFDBE4",
    text="#10253A",
    muted="#506678",
    primary="#066F80",
    primary_hover="#055B69",
    primary_text="#FFFFFF",
    success="#13703F",
    warning="#8A5A00",
    danger="#B3261E",
    info="#1259A8",
    success_bg="#E3F5EA",
    warning_bg="#FFF1D6",
    danger_bg="#FDE8E6",
    info_bg="#E4EEFA",
    focus="#055B69",
    selection="#CFE9EE",
)
PALETTES: Final = {"dark": DARK, "light": LIGHT}


def palette(theme: str) -> Palette:
    return PALETTES.get(theme, LIGHT)


def pick_family(candidates: tuple[str, ...], installed: set[str] | None = None) -> str:
    have = installed if installed is not None else set(QFontDatabase.families())
    for name in candidates:
        if name in have:
            return name
    return candidates[-1]


def app_font() -> QFont:
    font = QFont(pick_family(FONT_STACK))
    font.setPointSize(TYPE["body"])
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def mono_family() -> str:
    return pick_family(MONO_STACK)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.x contrast ratio between two #RRGGBB colours."""

    def lum(value: str) -> float:
        channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    a, b = sorted((lum(foreground), lum(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def tone_colors(theme: str, tone: str) -> tuple[str, str]:
    """(foreground, background) of a status tone: ok / warn / danger / info / idle."""
    p = palette(theme)
    return {
        "ok": (p.success, p.success_bg),
        "warn": (p.warning, p.warning_bg),
        "danger": (p.danger, p.danger_bg),
        "info": (p.info, p.info_bg),
    }.get(tone, (p.muted, p.surface_alt))


_ARROWS: dict[str, tuple[str, str]] = {}


def arrow_images(theme: str) -> tuple[str, str]:
    """Chevron images (down, up) used by combo boxes and spin boxes; written once per theme."""
    if theme in _ARROWS:
        return _ARROWS[theme]
    folder = Path(tempfile.gettempdir()) / "doctorcar-ui"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, points in (("down", ((3, 5), (8, 10), (13, 5))), ("up", ((3, 10), (8, 5), (13, 10)))):
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(palette(theme).muted), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(x, y) for x, y in points])
        painter.end()
        target = folder / f"{theme}-{name}.png"
        pixmap.save(str(target))
        paths.append(target.as_posix())
    _ARROWS[theme] = (paths[0], paths[1])
    return _ARROWS[theme]


def build_stylesheet(theme: str, scale: float = 1.0) -> str:
    """The one stylesheet of the application. ``scale`` multiplies font sizes (display zoom)."""
    p = palette(theme)
    family = pick_family(FONT_STACK)
    mono = mono_family()

    def pt(name: str) -> str:
        return f"{TYPE[name] * scale:.1f}pt"

    r = RADIUS
    down, up = arrow_images(theme)
    return f"""
* {{ font-family: '{family}'; font-size: {pt("body")}; }}
QMainWindow, QWidget#root, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {p.bg}; color: {p.text}; }}
QLabel {{ background: transparent; color: {p.text}; }}
QLabel[role="title"] {{ font-size: {pt("title")}; font-weight: 700; }}
QLabel[role="display"] {{ font-size: {pt("display")}; font-weight: 700; }}
QLabel[role="subtitle"] {{ font-size: {pt("subtitle")}; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="caption"] {{ color: {p.muted}; font-size: {pt("caption")}; }}
QLabel[role="mono"] {{ font-family: '{mono}'; }}
QLabel[role="metric"] {{ font-size: {pt("display")}; font-weight: 700; font-family: '{mono}'; }}
QFrame[card="true"] {{ background: {p.surface}; border: 1px solid {p.border};
    border-radius: {r["lg"]}px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[card="true"][state="active"] {{ border: 1px solid {p.primary}; }}
QFrame[card="true"][state="stale"] {{ background: {p.surface_alt}; }}
QWidget#sidebar {{ background: {p.sidebar}; border-radius: {r["lg"]}px; }}
QWidget#sidebar QLabel {{ color: {p.sidebar_text}; }}
QWidget#sidebar QLabel[role="caption"] {{ color: {p.sidebar_muted}; }}
QWidget#header {{ background: transparent; }}
QLabel#notice {{ background: {p.warning_bg}; color: {p.warning}; border: 1px solid {p.warning};
    border-radius: {r["md"]}px; padding: 8px 12px; }}
QLabel#error {{ background: {p.danger_bg}; color: {p.danger}; border: 1px solid {p.danger};
    border-radius: {r["md"]}px; padding: 8px 12px; }}
QFrame#banner {{ border-radius: {r["md"]}px; padding: 2px; }}
QFrame#banner[tone="warn"] {{ background: {p.warning_bg}; border: 1px solid {p.warning}; }}
QFrame#banner[tone="danger"] {{ background: {p.danger_bg}; border: 1px solid {p.danger}; }}
QFrame#banner QLabel {{ background: transparent; }}
QFrame#banner[tone="warn"] QLabel {{ color: {p.warning}; }}
QFrame#banner[tone="danger"] QLabel {{ color: {p.danger}; }}
QLabel#pill {{ border-radius: 11px; padding: 3px 10px; font-weight: 600;
    background: {p.surface_alt}; color: {p.muted}; border: 1px solid {p.border}; }}
QLabel#pill[tone="ok"] {{ background: {p.success_bg}; color: {p.success}; border-color: {p.success}; }}
QLabel#pill[tone="warn"] {{ background: {p.warning_bg}; color: {p.warning}; border-color: {p.warning}; }}
QLabel#pill[tone="danger"] {{ background: {p.danger_bg}; color: {p.danger}; border-color: {p.danger}; }}
QLabel#pill[tone="info"] {{ background: {p.info_bg}; color: {p.info}; border-color: {p.info}; }}
QPushButton {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.border};
    border-radius: {r["sm"]}px; padding: 8px 16px; min-height: 20px; }}
QPushButton:hover {{ border-color: {p.primary}; }}
QPushButton:pressed {{ background: {p.selection}; padding-top: 9px; padding-bottom: 7px; }}
QPushButton:focus {{ border: 2px solid {p.focus}; }}
QPushButton:disabled {{ color: {p.muted}; background: {p.bg}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{ background: {p.primary}; color: {p.primary_text};
    border: 1px solid {p.primary}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {p.primary_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.surface_alt}; color: {p.muted};
    border-color: {p.border}; }}
QPushButton[variant="danger"] {{ background: {p.danger_bg}; color: {p.danger};
    border: 1px solid {p.danger}; font-weight: 600; }}
QPushButton[variant="danger"]:disabled {{ background: {p.bg}; color: {p.muted}; border-color: {p.border}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_alt}; }}
QWidget#sidebar QPushButton[variant="ghost"] {{ color: {p.sidebar_muted}; }}
QWidget#sidebar QPushButton[variant="ghost"]:hover {{ color: {p.sidebar_text}; background: {p.sidebar_active}; }}
QTableCornerButton::section {{ background: {p.surface_alt}; border: none; }}
QPushButton[variant]:focus {{ border: 2px solid {p.focus}; }}
QPushButton[variant="nav"] {{ background: transparent; color: {p.sidebar_muted}; border: none; }}
QPushButton[variant="nav"]:hover {{ color: {p.sidebar_text}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {p.surface}; color: {p.text};
    border: 1px solid {p.border}; border-radius: {r["sm"]}px; padding: 7px 10px; min-height: 20px;
    selection-background-color: {p.selection}; selection-color: {p.text}; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {p.primary}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {p.focus}; padding: 6px 9px; }}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {p.muted}; background: {p.bg}; }}
QComboBox QAbstractItemView {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
    selection-background-color: {p.selection}; selection-color: {p.text}; outline: none; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url({down}); width: 14px; height: 14px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 20px; border: none; background: transparent; }}
QCheckBox {{ spacing: 10px; color: {p.text}; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {p.muted};
    border-radius: 5px; background: {p.surface}; }}
QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; }}
QCheckBox:focus {{ color: {p.primary}; }}
QListWidget {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
    border-radius: {r["md"]}px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; }}
QListWidget::item:selected {{ background: {p.selection}; color: {p.text}; }}
QListWidget#nav {{ background: transparent; border: none; }}
QTableWidget, QTextEdit, QPlainTextEdit {{ background: {p.surface}; color: {p.text};
    border: 1px solid {p.border}; border-radius: {r["md"]}px; gridline-color: {p.border};
    selection-background-color: {p.selection}; selection-color: {p.text}; }}
QTableWidget::item {{ padding: 6px; }}
QTableWidget::item:selected {{ background: {p.selection}; color: {p.text}; }}
QHeaderView::section {{ background: {p.surface_alt}; color: {p.text}; border: none;
    border-bottom: 1px solid {p.border}; padding: 10px 8px; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {p.surface_alt}; color: {p.text}; border: 1px solid {p.border}; padding: 6px; }}
QProgressBar {{ background: {p.surface_alt}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {p.primary}; border-radius: 3px; }}
QDialog, QMessageBox, QFileDialog {{ background: {p.bg}; color: {p.text}; }}
"""
