"""DC-UX-001 performance probe (native Qt platform, temp DB only). Usage: ux_perf.py <label>

Measures import time, window construction, backend-ready time, page-navigation latency, per-sample UI update cost,
and working-set memory. Writes docs/evidence/ui-ux-redesign/perf-<label>.json.
"""

import ctypes
import json
import os
import statistics
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

T0 = time.perf_counter()
os.environ.pop("QT_QPA_PLATFORM", None)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
T_QT = time.perf_counter()
from doctorcar.ui.main_window import MainWindow  # noqa: E402

T_IMPORT = time.perf_counter()


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_psapi, _kernel = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
_kernel.GetCurrentProcess.restype = wintypes.HANDLE


def rss_mb() -> float:
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    _psapi.GetProcessMemoryInfo(_kernel.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6


def pump(seconds=0.0, until=None, limit=30.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.002)
    return bool(until and until())


label = sys.argv[1]
db = Path(tempfile.mkdtemp(prefix="dc-ux-perf-")) / "p.sqlite3"
t = time.perf_counter()
w = MainWindow(db)
t_construct = time.perf_counter() - t
w.show()
pump(until=lambda: w.backend_ready)
t_ready = time.perf_counter() - t
pump(0.5)
mem_idle = rss_mb()
nav = []
for _ in range(8):
    for row in range(w.navigation.count()):
        a = time.perf_counter()
        w.navigation.setCurrentRow(row)
        app.processEvents()
        nav.append((time.perf_counter() - a) * 1000)
from doctorcar.sources.simulation import SimulationSource  # noqa: E402

src = SimulationSource(seed=1, scenario_family="multisensor", mode="NORMAL")
src.connect()
src.session_id = "perf"
src.start()
samples = []
while (s := src.read_measurements()) is not None:
    samples.append(s)
w.navigation.setCurrentRow(2)
upd = []
for s in samples[:400]:
    a = time.perf_counter()
    w.show_sample(s)
    app.processEvents()
    upd.append((time.perf_counter() - a) * 1000)
w.navigation.setCurrentRow(0)
upd0 = []
for s in samples[400:700]:
    a = time.perf_counter()
    w.show_sample(s)
    app.processEvents()
    upd0.append((time.perf_counter() - a) * 1000)
res = {
    "label": label,
    "import_qt_s": round(T_QT - T0, 3),
    "import_ui_s": round(T_IMPORT - T_QT, 3),
    "construct_window_s": round(t_construct, 3),
    "backend_ready_s": round(t_ready, 3),
    "process_to_ready_s": round(T_IMPORT - T0 + t_ready, 3),
    "nav_ms_mean": round(statistics.mean(nav), 2),
    "nav_ms_p95": round(sorted(nav)[int(len(nav) * 0.95)], 2),
    "sample_update_sensors_page_ms_mean": round(statistics.mean(upd), 2),
    "sample_update_sensors_page_ms_p95": round(sorted(upd)[int(len(upd) * 0.95)], 2),
    "sample_update_dashboard_ms_mean": round(statistics.mean(upd0), 2),
    "sample_update_dashboard_ms_p95": round(sorted(upd0)[int(len(upd0) * 0.95)], 2),
    "working_set_idle_mb": round(mem_idle, 1),
    "working_set_after_mb": round(rss_mb(), 1),
}
w.close()
pump(until=lambda: w.worker.isFinished())
out = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "ui-ux-redesign" / f"perf-{label}.json"
out.write_text(json.dumps(res, indent=2), encoding="utf8")
print(json.dumps(res, indent=2))
