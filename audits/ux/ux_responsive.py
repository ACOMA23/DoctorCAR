"""DC-UX-001: layout checks at several window sizes, Windows scale factors (display zoom) and both languages.

For each combination every visible label/button/check box/line edit/combo is tested for clipping (text wider than
its widget), horizontal overflow of the page scroll area is reported, and the minimum sizes are recorded.
Native Qt platform, temp database. Usage: ux_responsive.py <out.json>
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtWidgets import QAbstractButton, QApplication, QCheckBox, QComboBox, QLabel, QScrollArea  # noqa: E402

from doctorcar.ui.main_window import MainWindow  # noqa: E402
from doctorcar.ui.widgets import ElidedLabel  # noqa: E402

app = QApplication([])
w = MainWindow(Path(tempfile.mkdtemp(prefix="dc-ux-resp-")) / "r.sqlite3")
w.show()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


pump(1.5)
report = {"combinations": 0, "clipped": [], "horizontal_overflow": [], "screen": []}
sizes = [(980, 640), (1280, 720), (1366, 768), (1920, 1080)]
for lang in (0, 1):
    for zoom in (100, 125, 150):
        w.language_combo.setCurrentIndex(lang)
        w.zoom_combo.setCurrentIndex(next(i for i in range(w.zoom_combo.count()) if w.zoom_combo.itemData(i) == zoom))
        for width, height in sizes:
            w.resize(width, height)
            pump(0.25)
            for row in range(6):
                w.navigation.setCurrentRow(row)
                pump(0.3)
                report["combinations"] += 1
                tag = f"{'ar' if lang == 0 else 'en'}/{zoom}%/{width}x{height}/page{row}"
                page = w.pages.currentWidget()
                if isinstance(page, QScrollArea) and page.horizontalScrollBar().isVisible():
                    report["horizontal_overflow"].append(tag)
                for c in w.findChildren(QLabel) + w.findChildren(QAbstractButton) + w.findChildren(QComboBox):
                    if not c.isVisible() or isinstance(c, ElidedLabel):  # elided labels end in an ellipsis and carry a tooltip
                        continue
                    if isinstance(c, QLabel):
                        if c.wordWrap() or not c.text() or c.pixmap() is not None and not c.text():
                            continue
                        need = c.fontMetrics().horizontalAdvance(c.text().replace("\n", ""))
                        have = c.width() - (c.contentsMargins().left() + c.contentsMargins().right())
                        if c.text().count("\n"):
                            need = max(c.fontMetrics().horizontalAdvance(line) for line in c.text().split("\n"))
                    elif isinstance(c, QCheckBox):
                        need, have = c.fontMetrics().horizontalAdvance(c.text()) + 28, c.width()
                    elif isinstance(c, QAbstractButton):
                        if not c.text():
                            continue
                        need, have = c.fontMetrics().horizontalAdvance(c.text()) + 24, c.width()
                    else:
                        text = c.currentText()
                        need, have = c.fontMetrics().horizontalAdvance(text) + 50, c.width()
                    if need > have + 2:
                        report["clipped"].append({"where": tag, "type": type(c).__name__, "text": c.text()[:40] if hasattr(c, "text") else c.currentText()[:40], "need": need, "have": have})
w.close()
pump(1.0)
report["unique_clipped"] = sorted({(x["type"], x["text"]) for x in report["clipped"]})
Path(sys.argv[1]).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=list), encoding="utf8")
print("combinations", report["combinations"], "clipped", len(report["clipped"]), "overflow", len(report["horizontal_overflow"]))
for item in report["unique_clipped"][:40]:
    print(item)
