"""Diagnostic: does a TCP loopback session deliver live samples to the window, and what do the labels say after the device dies?"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from doctorcar.ui.main_window import MainWindow
app = QApplication.instance() or QApplication([])
def pump(seconds=0.0, until=None, limit=60.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until(): return True
        time.sleep(0.004)
    return bool(until and until())
tmp = Path(tempfile.mkdtemp(prefix="dc-tcp-"))
w = MainWindow(tmp / "t.sqlite3"); w.show(); pump(until=lambda: w.backend_ready, limit=20)
ready = tmp / "r.json"
p = subprocess.Popen([sys.executable, "-m", "doctorcar.protocol.network_simulator", "--port", "0", "--speed", "30", "--history", str(tmp / "h.json"), "--ready", str(ready)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
pump(until=lambda: ready.exists() and ready.stat().st_size > 2, limit=20)
port = json.loads(ready.read_text())["port"]
idx = lambda c, d: next(i for i in range(c.count()) if c.itemData(i) == d)
w.source_combo.setCurrentIndex(idx(w.source_combo, "network")); w.host_input.setText("127.0.0.1"); w.network_port.setValue(port)
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
pump(until=lambda: not w.source_combo.isEnabled(), limit=20)
def snap(tag):
    l = w.latest
    print(tag, "| status:", w.status_label.text(), "| latest:", (l.source.value, l.sequence_number, l.timestamp_ms) if l else None, "| age:", w.age.text(), "| err:", w.error_label.text()[:60] if w.error_label.isVisible() else "", "| conn:", w.connection_details.text().replace("\n", " ")[:60], flush=True)
for t in range(5):
    pump(1.0); snap(f"t+{t+1}s")
p.kill(); p.communicate(timeout=10); print("--- device killed")
for t in range(8):
    pump(1.0); snap(f"after+{t+1}s")
w.close(); pump(until=lambda: w.worker.isFinished(), limit=10)
