"""Reproducible DC-CR-004 event benchmark and real separate-process Qt/TCP audit."""

import argparse
import json
import os
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.experiment import DATASET, write_json
from doctorcar.analysis.model import MODEL_DIR
from doctorcar.core.interfaces import Capabilities, DataSource
from doctorcar.core.models import Sample
from doctorcar.core.sensor_registry import NUMERIC_IDS
from doctorcar.core.session import Session
from doctorcar.diagnostics.human_report import (
    build_report_model,
    render_simple,
    render_technical,
)
from doctorcar.storage.sqlite_repository import SQLiteRepository
from doctorcar.ui.main_window import MainWindow
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

OUT = Path("docs/evidence/dc-cr-004")


class TripSource(DataSource):
    def __init__(self, samples):
        self.samples = samples
        self.index = 0

    def connect(self):
        self.index = 0
        self.state = "CONNECTED"
        self.exhausted = False

    def get_capabilities(self):
        return Capabilities(frozenset(NUMERIC_IDS), "SIMULATION")

    def read_measurements(self):
        if self.index == len(self.samples):
            self.exhausted = True
            return None
        result = self.samples[self.index]
        self.index += 1
        return result


class NoRules:
    def evaluate_trigger(self, sample, issues):
        return ()


def benchmark():
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf8"))
    results = []
    timings = []
    for trip in (t for t in manifest["trips"] if t["split"] == "test"):
        samples = [
            Sample.from_dict(json.loads(line))
            for line in (DATASET / f"{trip['trip']}.jsonl")
            .read_text(encoding="utf8")
            .splitlines()
        ]
        case = {"trip": trip["trip"], "injections": trip["scenarios"], "results": {}}
        for method in ("rules", "ml", "combined"):
            with SQLiteRepository(Path(":memory:")) as repo:
                source = TripSource(samples)
                session = Session(
                    source,
                    repo,
                    analyzer=AnomalyAnalyzer() if method != "rules" else None,
                )
                session.start()
                if method == "ml":
                    session.detector = NoRules()
                while not source.exhausted:
                    session.step()
                session.stop()
                rows = sorted(
                    [r for r in repo.list_events() if r["kind"] != "DATA_QUALITY"],
                    key=lambda r: r["trigger_ms"],
                )
                unmatched = set(range(len(trip["scenarios"])))
                tp = fp = 0
                delays = []
                for row in rows:
                    candidates = [
                        i
                        for i in unmatched
                        if trip["scenarios"][i]["start_ms"]
                        <= row["trigger_ms"]
                        < trip["scenarios"][i]["start_ms"]
                        + trip["scenarios"][i]["duration_ms"]
                    ]
                    if candidates:
                        index = min(candidates)
                        unmatched.remove(index)
                        tp += 1
                        delays.append(
                            (row["trigger_ms"] - trip["scenarios"][index]["start_ms"])
                            / 1000
                        )
                    else:
                        fp += 1
                full = 0
                for row in rows:
                    event = repo.get_event(row["event_id"])
                    full += int(
                        event.status == "COMPLETE"
                        and event.samples[0].timestamp_ms
                        == event.trigger.timestamp_ms - 30000
                        and event.samples[-1].timestamp_ms
                        == event.trigger.timestamp_ms + 30000
                    )
                case["results"][method] = {
                    "TP": tp,
                    "FP": fp,
                    "FN": len(unmatched),
                    "delays_seconds": delays,
                    "events": rows,
                    "full_60s_windows": full,
                    "accepted_samples": session.accepted,
                    "rejected_samples": session.rejected,
                }
                if method == "combined":
                    for r in repo.connection.execute("select data_json from analyses"):
                        data = json.loads(r[0])
                        if "inference_ms" in data:
                            timings.append(data["inference_ms"])
        results.append(case)
        print("BENCHMARK", trip["trip"], flush=True)
    hours = len(results) * 155 / 3600
    aggregate = {}
    for method in ("rules", "ml", "combined"):
        values = [c["results"][method] for c in results]
        tp, fp, fn = (sum(v[k] for v in values) for k in ("TP", "FP", "FN"))
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        aggregate[method] = {
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "precision": p,
            "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0,
            "false_alarms_per_simulated_hour": fp / hours,
            "full_recordings": sum(v["full_60s_windows"] for v in values),
            "total_events": sum(len(v["events"]) for v in values),
            "delays_seconds": [d for v in values for d in v["delays_seconds"]],
        }
    normal_alarms = sum(
        len(c["results"]["combined"]["events"]) for c in results if not c["injections"]
    )
    result = {
        "unit": "Emitted event, greedy one-to-one active injection interval matching; duplicates/outside interval FP. Not causal accuracy.",
        "hours": hours,
        "aggregate": aggregate,
        "normal_trip_alarms": normal_alarms,
        "AT-E2E-01": "PASS" if normal_alarms == 0 else "FAIL",
        "inference_ms": {
            "mean": sum(timings) / len(timings),
            "max": max(timings),
            "count": len(timings),
        },
        "trips": results,
    }
    write_json(OUT / "event-benchmark.json", result)
    return result


def wait(app, predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    if not predicate():
        raise TimeoutError("GUI audit condition timed out")


def e2e():
    run = Path(f"data/cr004-audit-{time.time_ns()}").resolve()
    run.mkdir(parents=True)
    ready = run / "ready.json"
    log = (OUT / "network-process.log").open("w", encoding="utf8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "doctorcar.protocol.network_simulator",
            "--port",
            "0",
            "--history",
            str(run / "device-history.json"),
            "--ready",
            str(ready),
            "--speed",
            "100",
            "--scenario",
            "S02",
        ],
        stdout=log,
        stderr=log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    app = QApplication.instance() or QApplication([])
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    database = run / "network.sqlite3"
    window = None
    try:
        wait(app, ready.exists, 10)
        port = json.loads(ready.read_text())["port"]
        window = MainWindow(database)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        wait(app, lambda: window.backend_ready)
        window.source_combo.setCurrentIndex(window.source_combo.findData("network"))
        window.network_port.setValue(port)
        window.ai_enabled.setChecked(True)
        window.navigation.setCurrentRow(1)
        app.processEvents()
        window.grab().save(str(OUT / "network-source-ar.png"))
        ticks.clear()
        window.start_button.click()
        wait(
            app,
            lambda: window.latest is not None and window.latest.timestamp_ms >= 155000,
            70,
        )
        window.stop_button.click()
        wait(app, lambda: window.source_combo.isEnabled())
        # Worker holds the owning DB connection, ask it to render the selected stored event.
        with SQLiteRepository(database) as repo:
            rows = repo.list_events()
            candidates = [
                r
                for r in rows
                if 60000 <= r["trigger_ms"] <= 95000
                and r["status"] == "COMPLETE"
                and repo.get_event_analysis(r["event_id"])
            ]
            selected = next(
                r
                for r in candidates
                if repo.get_event_analysis(r["event_id"]).get("xai", {}).get("status")
                == "AVAILABLE"
            )
            event = repo.get_event(selected["event_id"])
            analysis = repo.get_event_analysis(event.event_id)
            report = build_report_model(
                event, analysis, repo.get_detections(event.event_id)
            )
            assert len(event.samples) == 301
            assert event.samples[0].timestamp_ms == event.trigger.timestamp_ms - 30000
            assert event.samples[-1].timestamp_ms == event.trigger.timestamp_ms + 30000
            assert len([r for r in rows if r["origin"] == "HISTORICAL"]) == 2
            assert (
                repo.connection.execute("pragma integrity_check").fetchone()[0] == "ok"
            )
            accepted = repo.connection.execute(
                "select count(*) from measurements where session_id=?",
                (event.session_id,),
            ).fetchone()[0]
            assert accepted == 776
            write_json(OUT / "example-report.json", report.to_dict())
            write_json(OUT / "example-event.json", event.to_dict())
            (OUT / "example-simple-ar.txt").write_text(
                render_simple(report), encoding="utf8"
            )
            (OUT / "example-technical-en.txt").write_text(
                render_technical(report, "en"), encoding="utf8"
            )
        window.worker.submit("report", event_id=event.event_id, language="ar")
        wait(
            app,
            lambda: (
                "العوامل" in window.simple_report_text.toPlainText()
                and window.navigation.currentRow() == 4
            ),
        )
        simple = window.simple_report_text.toPlainText()
        assert not window.report_text.isVisible()
        window.grab().save(str(OUT / "simple-report-ar.png"))
        window.technical_button.setChecked(True)
        window.time_plot.selector.setCurrentIndex(2)
        app.processEvents()
        window.grab().save(str(OUT / "technical-plot-ar.png"))
        window.language_combo.setCurrentIndex(1)
        window.theme_combo.setCurrentIndex(1)
        window.worker.submit("report", event_id=event.event_id, language="en")
        wait(
            app,
            lambda: "What did AI observe?" in window.simple_report_text.toPlainText(),
        )
        window.technical_button.setChecked(False)
        app.processEvents()
        window.grab().save(str(OUT / "simple-report-en-dark.png"))
        window.worker.shutdown()
        assert window.worker.wait(5000)
        window.close()
        window = MainWindow(database)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        wait(app, lambda: window.backend_ready)
        window.worker.submit("report", event_id=event.event_id, language="ar")
        wait(app, lambda: window.simple_report_text.toPlainText() == simple)
        window.grab().save(str(OUT / "report-restored.png"))
        gaps = [b - a for a, b in pairwise(ticks)]
        result = {
            "status": "PASS",
            "database": str(database),
            "server_pid": process.pid,
            "client_pid": os.getpid(),
            "event_id": event.event_id,
            "trigger_ms": event.trigger.timestamp_ms,
            "first_ms": event.samples[0].timestamp_ms,
            "last_ms": event.samples[-1].timestamp_ms,
            "samples": len(event.samples),
            "accepted_live_samples": accepted,
            "model_version": analysis["model_version"],
            "score": analysis["score"],
            "threshold": analysis["threshold"],
            "decision": analysis["decision"],
            "xai": analysis["xai"],
            "detections": report.detection_sources,
            "gui_timer_ticks": len(ticks),
            "max_gui_timer_gap_ms": max(gaps) * 1000,
            "restored_identical": True,
            "historical_events": 2,
            "firmware_build": "NOT_RUN_NO_SDK",
            "physical_device_verified": False,
            "vehicle_verified": False,
            "model_path": str(MODEL_DIR),
        }
        write_json(OUT / "e2e.json", result)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        timer.stop()
        if window is not None:
            window.worker.shutdown()
            window.worker.wait(5000)
            window.close()
        process.terminate()
        process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("benchmark", "e2e"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.mode == "benchmark":
        print(json.dumps(benchmark()["aggregate"], indent=2))
    else:
        e2e()
