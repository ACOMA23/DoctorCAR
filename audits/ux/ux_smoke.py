import os, sys, tempfile, time
from pathlib import Path
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtWidgets import QApplication
app = QApplication([])
from doctorcar.ui.main_window import MainWindow
db = Path(tempfile.mkdtemp()) / "s.sqlite3"
w = MainWindow(db); w.show()
end = time.monotonic() + 3
while time.monotonic() < end: app.processEvents(); time.sleep(0.01)
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
for lang in (0, 1):
    w.language_combo.setCurrentIndex(lang)
    for th in (0, 1):
        w.theme_combo.setCurrentIndex(th)
        for row in range(6):
            w.navigation.setCurrentRow(row)
            for _ in range(10): app.processEvents(); time.sleep(0.01)
            w.grab().save(str(out / f"{'ar' if lang==0 else 'en'}-{'light' if th==0 else 'dark'}-p{row}.png"))
w.close()
end = time.monotonic() + 3
while time.monotonic() < end and w.worker.isRunning(): app.processEvents(); time.sleep(0.01)
print("ok")
