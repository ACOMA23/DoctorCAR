"""DC-UX-001: latency from clicking Start (AI on) to the session running, in a fresh process.

mode "direct": MainWindow only (the pre-redesign startup: the AI model is imported lazily at the first start).
mode "launcher": Launcher with the AI warm-up thread (the new startup). Usage: ux_start_latency.py <mode>
"""
import json, os, sys, tempfile, time
from pathlib import Path
os.environ.pop("QT_QPA_PLATFORM", None)
mode = sys.argv[1]
t0 = time.perf_counter()
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication([])
db = Path(tempfile.mkdtemp(prefix="dc-lat-")) / "l.sqlite3"
def pump(until, limit=40.0):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        app.processEvents()
        if until(): return True
        time.sleep(0.002)
    return until()
if mode == "launcher":
    from doctorcar.ui.startup import Launcher
    launcher = Launcher(app, db, use_splash=False, interactive=False)
    launcher.start()
    assert pump(lambda: launcher.finished_ok)
    w = launcher.window
else:
    from doctorcar.ui.main_window import MainWindow
    w = MainWindow(db); w.show()
    assert pump(lambda: w.backend_ready)
t_ready = time.perf_counter() - t0
pump(lambda: False, 0.5) if False else None
w.ai_enabled.setChecked(True)
a = time.perf_counter()
QTest.mouseClick(w.start_button, Qt.MouseButton.LeftButton)
assert pump(lambda: w.running)
latency = time.perf_counter() - a
res = {"mode": mode, "process_to_ready_s": round(t_ready, 3), "start_click_to_running_s": round(latency, 3)}
QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton)
pump(lambda: not w.running)
w.close(); pump(lambda: w.worker.isFinished(), 10)
print(json.dumps(res))
