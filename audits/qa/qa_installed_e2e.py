"""Runs INSIDE a fresh virtual environment with the installed wheel (python -I, neutral cwd).
It must not import anything from the development tree. Usage: qa_installed_e2e.py <out.json> <shot.png>"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from importlib import resources
from pathlib import Path

out_path, shot_path = Path(sys.argv[1]), Path(sys.argv[2])
facts = {"python": sys.version.split()[0], "executable": sys.executable, "cwd": os.getcwd()}
import doctorcar  # noqa: E402

pkg = Path(doctorcar.__file__).resolve()
facts["package_file"] = str(pkg)
facts["from_site_packages"] = "site-packages" in str(pkg)
dev_root = os.path.normcase(os.environ.get("QA_DEV_ROOT", "?"))
facts["sys_path"] = list(sys.path)
facts["dev_tree_on_sys_path"] = [p for p in sys.path if os.path.normcase(p).startswith(dev_root)]
from doctorcar.analysis import model as m  # noqa: E402

facts["models_root"] = str(m.MODELS_ROOT)
facts["models_in_site_packages"] = "site-packages" in str(m.MODELS_ROOT)
facts["available_models"] = list(m.available_models())
facts["default_model"] = m.DEFAULT_MODEL
facts["schema_resource"] = (resources.files("doctorcar.protocol") / "device_protocol_v1.schema.json").is_file()
root = pkg.parent
bad = re.compile(r"[A-Za-z]:\\\\(Users|doccar)|C:/doccar|desktop/src|/c/doccar", re.I)
hits = []
for f in root.rglob("*.py"):
    for i, line in enumerate(f.read_text(encoding="utf8", errors="replace").splitlines(), 1):
        if bad.search(line):
            hits.append(f"{f.relative_to(root)}:{i}: {line.strip()[:90]}")
facts["absolute_dev_paths_in_installed_sources"] = hits
cp = subprocess.run([str(Path(sys.executable).parent / "doctorcar.exe"), "--help"], capture_output=True, text=True, timeout=60)
facts["entry_point_help_exit"] = cp.returncode
facts["entry_point_help_head"] = cp.stdout[:160]
for name in m.available_models():
    facts[f"load_{name}"] = m.AnomalyModel(name).metadata["model_version"]

# short run with AI + XAI into a brand-new database (no user data)
from doctorcar.analysis.analyzer import AnomalyAnalyzer  # noqa: E402
from doctorcar.analysis.explanation import explain  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.diagnostics.human_report import build_report_model, load_ai_context, render_simple  # noqa: E402
from doctorcar.sources.scenarios import ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

work = Path(out_path).parent
db = work / "installed-run.sqlite3"
for f in work.glob("installed-run.sqlite3*"):
    f.unlink()
src = SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S02", 60000, 35000),))
analyzer = AnomalyAnalyzer(m.AnomalyModel("cr004-iforest-v1"))  # v1 reacts to S02, exercising XAI
with SQLiteRepository(db) as repo:
    s = Session(src, repo, analyzer=analyzer)
    s.start()
    while not src.exhausted:
        s.step()
    s.stop()
    events = repo.list_events()
    ai_ev = next((r for r in events if (a := repo.get_event_analysis(r["event_id"])) and a.get("xai", {}).get("status") == "AVAILABLE"), None)
    facts["short_run"] = {"accepted": s.accepted, "events": [(r["kind"], r["status"]) for r in events], "xai_event": ai_ev["kind"] if ai_ev else None}
    ev = repo.get_event((ai_ev or events[0])["event_id"])
    analysis, status, later = load_ai_context(repo, ev)
    text = render_simple(build_report_model(ev, analysis, repo.get_detections(ev.event_id), status, later))
    facts["short_run"]["report_chars"] = len(text)
    facts["short_run"]["report_has_ai_section"] = "ماذا لاحظ الذكاء الاصطناعي" in text

# native GUI from the installed package
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

os.environ.pop("QT_QPA_PLATFORM", None)
from doctorcar.ui.main_window import MainWindow  # noqa: E402

app = QApplication([])


def pump(limit, until=None):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        app.processEvents()
        if until and until():
            return True
        time.sleep(0.005)
    return bool(until and until())


gdb = work / "installed-gui.sqlite3"
for f in work.glob("installed-gui.*"):
    f.unlink()
w = MainWindow(gdb)
w.show()
facts["gui_platform"] = app.platformName()
facts["gui_backend_ready"] = pump(15, lambda: w.backend_ready)
w.worker.submit("start", source="simulation", ai_enabled=True, seed=4100, speed=30.0, mode="FAULT_INJECTION", scenario_family="multisensor",
                scenarios=[asdict(ScenarioInstance("S02", 60000, 35000))])
facts["gui_event_complete"] = pump(90, lambda: any("COMPLETE" in " ".join(w.events_table.item(r, c).text() for c in range(9) if w.events_table.item(r, c)) or "مكتمل" in " ".join(w.events_table.item(r, c).text() for c in range(9) if w.events_table.item(r, c)) for r in range(w.events_table.rowCount())))
facts["gui_ai_label"] = w.ai_label.text()
w.worker.submit("stop")
pump(10, lambda: w.source_combo.isEnabled())
w.navigation.setCurrentRow(3)
pump(0.5)
if w.events_table.rowCount():
    item = w.events_table.item(0, 0)
    pos = w.events_table.visualItemRect(item).center()
    QTest.mouseClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    pump(0.2)
    QTest.mouseDClick(w.events_table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
facts["gui_report_opened"] = pump(15, lambda: w.pages.currentIndex() == 4 and bool(w.simple_report_text.toPlainText()))
facts["gui_report_chars"] = len(w.simple_report_text.toPlainText())
w.grab().save(str(shot_path))
w.close()
pump(10, lambda: w.worker.isFinished())
facts["gui_closed_cleanly"] = w.worker.isFinished()
out_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf8")
print("installed e2e written", out_path)
