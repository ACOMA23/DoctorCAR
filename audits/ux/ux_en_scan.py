"""Scan every label/button/combo/header/tooltip of the window in English mode for leftover Arabic (native Qt)."""
import os, re, sys, tempfile, time
from pathlib import Path
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QComboBox, QCheckBox, QLineEdit, QListWidget, QTableWidget, QWidget
from doctorcar.ui.main_window import MainWindow
AR = re.compile(r"[\u0600-\u06FF]")
app = QApplication([])
w = MainWindow(Path(tempfile.mkdtemp()) / "e.sqlite3"); w.show()
def pump(s):
    end = time.monotonic() + s
    while time.monotonic() < end: app.processEvents(); time.sleep(0.005)
pump(1.5)
w.language_combo.setCurrentIndex(1); pump(0.3)
found = []
for row in range(6):
    w.navigation.setCurrentRow(row); pump(0.15)
    for c in w.findChildren(QWidget):
        texts = []
        if isinstance(c, (QLabel, QPushButton, QCheckBox)): texts.append(c.text())
        if isinstance(c, QComboBox): texts += [c.itemText(i) for i in range(c.count())]
        if isinstance(c, QLineEdit): texts.append(c.placeholderText())
        if isinstance(c, QListWidget): texts += [c.item(i).text() for i in range(c.count())]
        if isinstance(c, QTableWidget): texts += [c.horizontalHeaderItem(i).text() for i in range(c.columnCount()) if c.horizontalHeaderItem(i)]
        if c.toolTip(): texts.append(c.toolTip())
        for t in texts:
            if AR.search(t) and c.objectName() != "faultList": found.append((row, type(c).__name__, t[:70]))
seen = sorted(set(found))
for x in seen: print(x)
print("ARABIC_IN_EN:", len(seen))
w.close(); pump(2)
