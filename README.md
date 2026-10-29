# DoctorCAR

**A Python/PySide6 desktop prototype that monitors vehicle-style sensor data, records what happened around transient events, and explains its findings — without pretending to diagnose a part.**

> **Status: prototype (M1).** All data today is **simulated, device-simulator or replayed**. No real vehicle, no real OBD/CAN adapter and no ESP32-S3 board has been used or verified. Nothing in this repository is a mechanical diagnosis.

## 1. Overview

DoctorCAR reads OBD-II-style measurements (RPM, speed, coolant temperature, engine load, throttle, intake pressure, MAF, intake temperature, fuel trims, module voltage, DTC list) from a pluggable data source, validates them, detects abnormal patterns, and stores a **30 s before / 30 s after** recording around each detection in SQLite. A report in Arabic or English explains what was observed, what supports it, what contradicts it, and which checks to perform.

## 2. The problem

Many vehicle faults are **transient**: they appear for seconds, set no DTC, and are gone when the car reaches a workshop. A scan tool shows only the present. DoctorCAR's goal is to keep the *evidence around the moment* (what every sensor did before and after) and to present it honestly, with limits stated.

## 3. Main features

| Area | What exists (verified in code/tests) |
| --- | --- |
| Desktop UI | Arabic-first (RTL) and English (LTR), light/dark themes, splash screen with real startup stages, dashboard, live sensor cards, event history, report view, settings |
| Data sources | Simulation, Replay file, protocol file, USB Serial (fake-port tested only), local TCP device simulator, simulated device history |
| Validation | Data-quality checks, physical plausibility bounds, unknown-sensor handling |
| Rule-based detection | Evidence rules `MS_*` over correlated sensors, with supporting/contradicting evidence and suggested checks |
| ML anomaly detection | IsolationForest, **advisory only** (default model `cr006-iforest-v3`) |
| XAI | Reference-replacement explanation of the model's own score |
| Event recording | T−30 s / T+30 s window per event in SQLite, `COMPLETE` or `PARTIAL` |
| Reports | Simple (owner) and technical (engineer) reports, AR/EN, export of a session to a Replay file |
| Protocol | JSON Lines v1 (`docs/DEVICE_PROTOCOL.md`, `schemas/`) |

## 4. Technology stack

Python ≥ 3.11 · PySide6 (Qt Widgets) · SQLite (standard library) · pyserial · jsonschema · optional ML extra: numpy, scikit-learn, joblib · pytest, ruff, mypy for development · ESP-IDF (C) for the **unbuilt** firmware source. Tested platform: **Windows 11 only**.

## 5. System architecture

```text
DataSource ──► DataQualityValidator ──► Session.step() ──► SQLiteRepository (measurements)
(simulation /                              │
 replay / file /                           ├─► EventDetector (rules) ─┐
 serial / TCP)                             └─► AnomalyAnalyzer (ML) ──┤  (advisory in the app)
                                                                      ▼
                                              EventRecorder + TimeRingBuffer (T±30 s)
                                                                      ▼
                                              SQLite: events, windows, analyses, reports
                                                                      ▼
BackendWorker (one QThread) ──signals──► MainWindow ──► reports (simple / technical)
```

`Session` is the single orchestrator. `BackendWorker` owns the source, the `Session` and the database connection in one thread; the GUI only displays.

## 6. How DoctorCAR works

1. `python -m doctorcar` creates the splash and a `Launcher`, which opens `MainWindow` and preloads the AI model in a background thread.
2. The user chooses a source and presses start; `BackendWorker` creates the source and a `Session`.
3. Each sample goes through validation → storage → rules (+ ML if enabled) → event recorder.
4. When a rule fires, the recorder collects 30 s before (from a ring buffer) and 30 s after, then saves the event.
5. The UI shows readings, events and a report built from the stored event.

## 7. IoT and device communication

- **Protocol:** JSON Lines v1 (HELLO → CAPABILITIES → SAMPLE/EVENT messages), validated by `protocol/codec.py` and a JSON schema.
- **Local TCP simulator:** `python -m doctorcar.protocol.network_simulator` serves a device over **127.0.0.1 only** (`NetworkDeviceSource` rejects non-loopback hosts); it can also upload historical events.
- **USB Serial source:** implemented and tested with fake ports only.
- **ESP32-S3 firmware:** C source under `firmware/` (ESP-IDF). **It has not been built or run on a board**; a known protocol-validation gap (A07) is documented, with an unapplied proposed patch in `docs/evidence/remediation/gate7_firmware/`. Real CAN/OBD, MicroSD, ADC and RTC are not implemented.

## 8. Rule-based diagnostics

`monitoring/evidence_rules.py` defines the `MS_*` rules (thermal, air/fuel, fuel response, airflow, supply voltage, combustion, signal quality). Each looks at relationships between sensors over a window (not at the injected fault name) and produces supporting evidence, contradicting evidence, missing data and suggested checks. **Rules produce the primary alerts.** Coverage on simulated single faults is 25 of 35 tested combinations; short or late faults at idle are known misses.

## 9. Machine-learning anomaly detection

`analysis/` builds causal 5 s feature windows (1 s stride), scores them with an IsolationForest (`analysis/model.py`; models in `analysis/models/`, loaded only if their SHA-256 matches `TRUSTED_SHA256`), and applies a persistence policy. Default model: `cr006-iforest-v3`, trained on synthetic data. **In the desktop app ML is advisory** (`Session(ml_alerts=False)`): it never opens an event by itself, only supports an event a rule opened. On an independent synthetic test it detects few events on its own (7.5 % event recall, 0 false alarms) — see `docs/evidence/remediation/ML_BEFORE_AFTER.md`. It is not evidence of a damaged part.

## 10. Explainable AI (XAI)

`analysis/explanation.py` replaces groups of features with a reference background and reports how much each group changes the **model's own score**. It only explains `ANOMALOUS` decisions, refuses results from a different model, and states that the factors are *model effects, not mechanical causes*.

## 11. Event recording — 30 s before and after

`EventRecorder` keeps a `TimeRingBuffer` of the last 30 s. On a detection at time T it stores samples from T−30 s to T+30 s. If the trip ends earlier the event is saved as `PARTIAL`. A new event of the same kind inside an open window is merged; one starting exactly at T+30 s gets its own event.

## 12. Simulation and testing

`sources/simulation.py` generates natural trips (155 s, repeating beyond that), correlated multi-sensor fault scenarios S01–S07 (`sources/scenarios.py`), random fault schedules and legacy faults. Ground truth is stored separately and used only for evaluation, never by the detectors. Tests: `desktop/tests` (unit, integration, e2e, per-change-request suites). Last recorded baseline: **316 passed, 0 failed, 0 skipped** (offscreen Qt).

## 13. Installation requirements

Windows 11, Python 3.11+ (tested with 3.14), PowerShell. Dependencies are declared in `desktop/pyproject.toml`; exact tested versions are in `desktop/requirements-lock.txt`.

## 14. Quick start (Windows PowerShell)

```powershell
Set-Location C:\doccar            # your clone path
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c desktop/requirements-lock.txt -e "./desktop[dev,ml]"
python -m pip check
```

(`[ml]` is needed for AI/XAI; without it the app still runs rules and recording.)

## 15. Running the desktop application

```powershell
.\.venv\Scripts\python.exe -m doctorcar --database data\demo.sqlite3
```

Use a throw-away `--database` path for experiments (the default is `data/doctorcar.sqlite3`, relative to the current directory). `--no-splash` skips the splash. To try the TCP device: run `.\.venv\Scripts\python.exe -m doctorcar.protocol.network_simulator --help`, start the simulator, then choose "network" in the Data sources page with host `127.0.0.1`.

## 16. Running tests

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -c desktop/pyproject.toml desktop/tests audits/test_m1_acceptance.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check desktop/src desktop/tests
.\.venv\Scripts\python.exe -m mypy desktop/src --config-file desktop/pyproject.toml
```

Run from the repository root (one test reads a relative `data/` path). The full suite takes about 2.5 minutes. Some scripts under `audits/` and `scripts/` write evidence files; run them only deliberately. Do **not** run `analysis/benchmark.py train` or `experiment.py train` — they overwrite packaged models.

## 17. Project structure

| Path | Content |
| --- | --- |
| `desktop/src/doctorcar/core/` | `Session`, models, sensor registry |
| `…/sources/` | simulation, replay, serial, network, device simulator, scenarios |
| `…/monitoring/` | data quality, rules, event detector/recorder, ring buffer |
| `…/analysis/` | windows, model, analyzer, XAI, packaged models, benchmark tools |
| `…/diagnostics/` | evidence, hypotheses, report builders |
| `…/protocol/` | JSONL codec, schema, simulators |
| `…/storage/` | SQLite repository |
| `…/ui/` | `theme`, `widgets`, `splash`, `startup`, `main_window`, `worker`, localization |
| `desktop/tests/` | pytest suites |
| `firmware/` | ESP32-S3 ESP-IDF source (unbuilt) |
| `docs/` | control file, protocol spec, evidence, [codebase quick guide](docs/CODEBASE_QUICK_GUIDE.md) |
| `audits/`, `scripts/` | independent QA and helper scripts |

## 18. Current implementation status

The authoritative status is [`docs/DOCTORCAR_PROJECT_CONTROL.md`](docs/DOCTORCAR_PROJECT_CONTROL.md). Summary: M1 is **PARTIAL**. Implemented and tested in simulation: sensor pipeline, validation, rules, T±30 s recording, SQLite persistence, reports, advisory ML + XAI, TCP loopback device simulator, redesigned UI with splash screen (DC-UX-001, verified on Windows by native runs and a wheel install). Evidence lives under `docs/evidence/`. The full Arabic developer guide is kept at [`docs/README_AR_DEVELOPER_GUIDE.md`](docs/README_AR_DEVELOPER_GUIDE.md).

## 19. Known limitations

- No real vehicle, OBD/CAN adapter or ESP32-S3 board was used; firmware is unbuilt and untested.
- All evaluation is on synthetic data from one generator; results do not generalise to vehicles.
- ML finds few anomalies alone and is advisory; XAI explains the model, not a mechanical cause.
- Rule coverage is partial (short and late faults at idle are missed); a second fault of the same kind within an open 30 s window is merged.
- Windows only; Windows display-scaling and screen-reader behaviour not tested; animations were not visually verified on the test machine.
- TCP is loopback-only by design.

## 20. Roadmap

1. Build and test the firmware (ESP-IDF) and fix the A07 validation gap.
2. Hardware-in-the-loop tests with a real ESP32-S3 over USB/Wi-Fi.
3. Real CAN/OBD-II read-only acquisition (no write or DTC-clear commands).
4. Collect real driving data before retraining/evaluating ML.
5. Expandable report sections, severity levels once defined, packaging for end users.

## 21. License

**No license file exists in this repository.** Until the owner chooses one, all rights are reserved and no usage rights are granted.
