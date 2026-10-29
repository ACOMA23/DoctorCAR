"""QA-PKG / QA-E2E-012: build a wheel from the current sources, install it in a brand-new venv and
exercise the installed application outside the development tree."""

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, ROOT, Registry, rel, scratch  # noqa: E402

reg = Registry("gate9")
folder = EVIDENCE / "gate9"
folder.mkdir(parents=True, exist_ok=True)
work = scratch("package")
py = sys.executable
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "QT_QPA_PLATFORM")}
env["QA_DEV_ROOT"] = str(ROOT)


def run(cmd, **kw):
    t = time.monotonic()
    cp = subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)
    return cp, time.monotonic() - t


wheel_dir = work / "wheel"
for f in wheel_dir.glob("*") if wheel_dir.exists() else ():
    f.unlink()
wheel_dir.mkdir(exist_ok=True)
cp, dt = run([py, "-m", "pip", "wheel", str(ROOT / "desktop"), "--no-deps", "-w", str(wheel_dir)], timeout=900)
wheels = list(wheel_dir.glob("doctorcar-*.whl"))
reg.check("QA-PKG-001", "NFR-002", "Wheel builds from the current sources", "pip wheel ./desktop --no-deps", "a doctorcar-0.1.0 wheel is produced", cp.returncode == 0 and len(wheels) == 1,
          f"exit={cp.returncode} wheel={wheels[0].name if wheels else None} size={wheels[0].stat().st_size if wheels else 0}", started=time.monotonic() - dt)
whl = wheels[0]
names = zipfile.ZipFile(whl).namelist()
needed = ["doctorcar/analysis/models/cr005-iforest-v2/model.joblib", "doctorcar/analysis/models/cr005-iforest-v2/metadata.json", "doctorcar/analysis/models/cr004-iforest-v1/model.joblib",
          "doctorcar/analysis/models/cr004-iforest-v1/metadata.json", "doctorcar/protocol/device_protocol_v1.schema.json"]
missing = [n for n in needed if n not in names]
extras = [n for n in names if n.startswith(("tests/", "audits/", "data/", "firmware/"))]
reg.check("QA-PKG-002", "NFR-002", "Wheel contains both models, metadata and the protocol schema; no tests, data or firmware leak in", "inspect wheel zip",
          "required resources present; no tests/audits/data/firmware entries", not missing and not extras, f"files={len(names)} missing={missing} unexpected={extras}")
venv = work / "qa-venv"
if venv.exists():
    import shutil

    shutil.rmtree(venv, ignore_errors=True)
cp, dt = run([py, "-m", "venv", str(venv)], timeout=300)
vpy = venv / "Scripts" / "python.exe"
spec = f"doctorcar[ml] @ file:///{whl.as_posix()}"
cp2, dt2 = run([str(vpy), "-m", "pip", "install", spec, "-c", str(ROOT / "desktop" / "requirements-lock.txt"), "-q"], timeout=1500)
chk, _ = run([str(vpy), "-m", "pip", "check"], timeout=120)
lst, _ = run([str(vpy), "-m", "pip", "list"], timeout=120)
(folder / "qa-venv-pip-list.txt").write_text(lst.stdout, encoding="utf8")
reg.check("QA-PKG-003", "NFR-002", "Fresh virtual environment: install with [ml] extra and the lock file; pip check clean", "python -m venv; pip install wheel[ml] -c requirements-lock.txt",
          "install exit 0; no broken requirements", cp2.returncode == 0 and chk.returncode == 0, f"install_exit={cp2.returncode} ({dt2:.0f}s) pip_check='{chk.stdout.strip()[:60]}' {cp2.stderr.strip()[-200:]}", rel(folder / "qa-venv-pip-list.txt"))
out_json, shot = folder / "installed-e2e.json", folder / "screenshots" / "installed-app-report.png"
shot.parent.mkdir(exist_ok=True)
if cp2.returncode == 0:
    neutral = work / "neutral"
    neutral.mkdir(exist_ok=True)
    cp3, dt3 = run([str(vpy), "-I", str(ROOT / "audits" / "qa" / "qa_installed_e2e.py"), str(out_json), str(shot)], cwd=str(neutral), timeout=900)
    (folder / "installed-e2e.log").write_text(cp3.stdout + "\n" + cp3.stderr, encoding="utf8")
    if out_json.exists():
        f = json.loads(out_json.read_text("utf8"))
        reg.check("QA-PKG-004", "NFR-002", "Installed package runs from site-packages, finds its models and schema, and does not depend on the development tree",
                  "python -I from a neutral folder", "package and models under site-packages; dev tree not on sys.path; no absolute dev paths in installed sources; schema resource present",
                  f["from_site_packages"] and f["models_in_site_packages"] and not f["dev_tree_on_sys_path"] and not f["absolute_dev_paths_in_installed_sources"] and f["schema_resource"],
                  json.dumps({k: f[k] for k in ("package_file", "models_root", "available_models", "default_model", "dev_tree_on_sys_path", "schema_resource", "absolute_dev_paths_in_installed_sources")}, ensure_ascii=False)[:600], rel(out_json))
        reg.check("QA-PKG-005", "NFR-002", "Console entry point works and both models load in the installed environment", "doctorcar --help; AnomalyModel(v1/v2)",
                  "exit 0 and versions reported", f["entry_point_help_exit"] == 0 and all(f.get(f"load_{n}") for n in f["available_models"]), f"help_exit={f['entry_point_help_exit']} loaded={[f.get('load_' + n) for n in f['available_models']]}", rel(out_json))
        sr = f["short_run"]
        reg.check("QA-E2E-012", "NFR-002/AI-005", "Fresh install: simulation with ML and XAI, new database, report with AI section",
                  "installed package: S02 session with model v1 (exercises XAI), report render", "776 accepted, XAI-bearing event, report includes the AI section",
                  sr["accepted"] == 776 and sr["xai_event"] is not None and sr["report_has_ai_section"], json.dumps(sr, ensure_ascii=False), rel(out_json))
        reg.check("QA-E2E-012b", "NFR-002/FR-010", "Fresh install: native GUI starts, runs a faulty simulation with AI, shows an event, opens the report and closes cleanly",
                  "MainWindow from site-packages on a new database; S02; double-click event", "backend ready, event complete, report opened, worker finished",
                  f["gui_backend_ready"] and f["gui_event_complete"] and f["gui_report_opened"] and f["gui_closed_cleanly"] and f["gui_platform"] == "windows",
                  json.dumps({k: f[k] for k in ("gui_platform", "gui_backend_ready", "gui_event_complete", "gui_ai_label", "gui_report_opened", "gui_report_chars", "gui_closed_cleanly")}, ensure_ascii=False), rel(shot))
    else:
        reg.add("QA-PKG-004", "NFR-002", "Installed package run", "python -I qa_installed_e2e.py", "JSON facts", f"script failed: {(cp3.stderr or cp3.stdout)[-400:]}", "FAIL", rel(folder / "installed-e2e.log"))
else:
    reg.add("QA-PKG-004", "NFR-002", "Installed package run", "-", "-", f"install failed: {cp2.stderr[-300:]}", "BLOCKED")
reg.save()
