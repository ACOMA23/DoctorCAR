# DoctorCAR — QA Master Plan (DC-QA-001)

نوع المستند: خطة اختبار ونتائجها الفعلية. كل حالة هنا لها ملف نتائج (`results.json`) تحت `docs/evidence/full-qa/<gate>/`؛ ولا تُسجَّل PASS دون مخرج فعلي مطابق لمعيار نجاح محدد.

## 1. الأهداف

1. التحقق من سلوك التطبيق الحقيقي (واجهة Windows الأصلية) لا الكود وحده.
2. التحقق من صحة القراءات وعلاقات الحساسات ودقة تأثير الأعطال المحقونة.
3. التحقق من الكشف (قواعد/ML)، XAI، التقارير، التسجيل T±30، قاعدة SQLite.
4. التحقق من IoT والبروتوكول والتثبيت على بيئة نظيفة، ومراجعة Firmware ساكنًا.
5. تسجيل العيوب بخطوات إعادة الإنتاج وخطة إصلاح قابلة للتنفيذ.

## 2. النطاق وما خارجه

**داخل النطاق:** تطبيق `doctorcar` 0.1.0 (Python/PySide6)، النموذجان v1/v2 (الافتراضي v2)، المحاكي، البروتوكول، SQLite، الحزمة، مصدر Firmware (قراءة).
**خارج النطاق/غير ممكن هنا:** بناء Firmware (لا ESP-IDF)، أي لوحة أو مركبة أو CAN أو Wi-Fi أو MicroSD، اختبار بصري يدوي طويل على أحجام DPI متعددة، قارئ الشاشة.

## 3. الإصدارات والبيئة

- التطبيق: doctorcar 0.1.0؛ النموذج الافتراضي `cr005-iforest-v2` (sha256 03153e0d…d85d87)؛ v1 `cr004-iforest-v1` (0970cd00…97a7).
- Python 3.14.6، Windows-11-10.0.26200-SP0، numpy 2.5.4، scikit-learn 1.9.1، joblib 1.6.0، PySide6 6.12.0، pytest 9.2.0.
- منصة Qt: `windows` (نافذة أصلية) بشاشة 1536×864؛ التفاعل عبر أحداث QTest على الودجات الحقيقية (وليس UI Automation على مستوى النظام)؛ اللقطات من `QWidget.grab()` للنافذة نفسها.
- قواعد بيانات الاختبار مؤقتة ومعزولة تحت مجلد scratchpad؛ لم تُفتح قاعدة المستخدم `data/doctorcar.sqlite3` ولا يشير إليها أي سكربت QA.
- أدوات غير متوفرة: ESP-IDF/CMake/Ninja/gcc، psutil، pywinauto/pyautogui.

## 4. جرد الوظائف (Test Inventory)

عدد البنود الوظيفية المجرودة: **65**؛ التصنيف: Verified: 51، Partially Verified: 7، Not Implemented: 3، Failed: 2، Not Tested: 2.
عدد الدوال/الأصناف العامة في كود المنتج (AST): **293** موزعة: (root) 1، analysis 53، core 45، diagnostics 19، monitoring 23، protocol 19، sources 63، storage 26، ui 44.
تعريف التصنيف: **Verified** = كل الاختبارات المرتبطة PASS؛ **Partially Verified** = بعضها PASS/PARTIAL أو يوجد فشل جزئي؛ **Failed** = كلها FAIL؛ **Not Tested** = لا دليل؛ **Not Implemented** = الميزة غير موجودة في المنتج.

| # | المجال | الوظيفة | الاختبارات | الحالة |
| --- | --- | --- | --- | --- |
| 1 | APP | Application launch on the native Windows platform | QA-APP-001, QA-E2E-012b | **Verified** |
| 2 | APP | Console entry point (doctorcar --help) | QA-PKG-005 | **Verified** |
| 3 | UI | Sidebar navigation: 6 pages | QA-UI-002, QA-UI-030 | **Verified** |
| 4 | UI | Source center: fields shown per source / mode / family | QA-UI-003, QA-UI-004 | **Verified** |
| 5 | UI | Combo boxes (9): all items selectable | QA-UI-031 | **Verified** |
| 6 | UI | Spin boxes (7): range clamping and keyboard | QA-UI-032 | **Verified** |
| 7 | UI | Text fields and AI check box | QA-UI-033 | **Verified** |
| 8 | UI | Start / Stop buttons, source locking, second-session refusal | QA-UI-005, QA-UI-006, QA-UI-009, QA-UI-020 | **Verified** |
| 9 | UI | Live sensor table updates | QA-UI-005, QA-SENSOR-003 | **Verified** |
| 10 | UI | AI status card (state, score, model version) | QA-UI-008 | **Verified** |
| 11 | UI | Event list and 'تحديث السجل' button | QA-UI-034 | **Verified** |
| 12 | UI | Open an event report (double-click and button) | QA-UI-010, QA-UI-035 | **Verified** |
| 13 | UI | Technical details toggle and time-series plot | QA-UI-011 | **Verified** |
| 14 | UI | Verify source / connection button | QA-UI-038, QA-UI-041, QA-UI-014, QA-UI-015 | **Partially Verified** |
| 15 | UI | Browse file dialog (real dialog) | QA-UI-037 | **Verified** |
| 16 | UI | Export session to Replay (real dialog) and Replay from the UI | QA-UI-036, QA-UI-039 | **Partially Verified** |
| 17 | UI | Refresh serial ports button | QA-UI-040 | **Verified** |
| 18 | UI | Arabic/English, RTL/LTR, no leftover Arabic in English mode | QA-UI-012, QA-UI-013 | **Verified** |
| 19 | UI | Light / Dark theme and settings persistence across restart | QA-UI-018, QA-E2E-011 | **Verified** |
| 20 | UI | Window close shuts the worker down | QA-UI-017 | **Verified** |
| 21 | UI | Responsiveness during a running session | QA-UI-007, QA-PERF-006 | **Verified** |
| 22 | UI | No stale live data after restart | QA-UI-019 | **Verified** |
| 23 | UI | Error messages for invalid input | QA-UI-014, QA-UI-015, QA-UI-016, QA-UI-023 | **Verified** |
| 24 | UI | Menu bar | — | **Not Implemented** |
| 25 | UI | Keyboard shortcuts | — | **Not Implemented** |
| 26 | UI | System theme mode | — | **Not Implemented** |
| 27 | SENSOR | Sensor registry (12 entries, units) | QA-SENSOR-001 | **Verified** |
| 28 | SENSOR | Reading type, unit, quality and timing over a full trip | QA-SENSOR-002 | **Verified** |
| 29 | SENSOR | Value-exact chain: simulation -> Session -> SQLite | QA-SENSOR-003 | **Verified** |
| 30 | SENSOR | Validator: missing / unsupported / range / stale / duplicate / backward | QA-SENSOR-004 | **Verified** |
| 31 | SENSOR | Operating relations across cold/warm/scale variants | QA-SENSOR-005, QA-SENSOR-006 | **Verified** |
| 32 | SIM | Determinism by seed and trip length | QA-SIM-001, QA-SIM-002 | **Verified** |
| 33 | SIM | Fault scenarios S01..S07: affected sensors and direction | QA-SIM-011, QA-SIM-012, QA-SIM-013, QA-SIM-014, QA-SIM-015, QA-SIM-016, QA-SIM-017, QA-SIM-030, QA-SIM-031, QA-SIM-032 | **Verified** |
| 34 | SIM | Fault durations (5 s, 90 s) and recovery | QA-SIM-033, QA-SIM-034 | **Verified** |
| 35 | SIM | Simultaneous faults and conflict rejection | QA-SIM-035 | **Verified** |
| 36 | SIM | RANDOM_FAULTS 30 s cycles and ground-truth schedule | QA-SIM-036, QA-E2E-005 | **Verified** |
| 37 | SIM | Simulation longer than the 155 s driving profile | QA-SIM-037 | **Failed** |
| 38 | EVENT | T-30 / T+30 recording at 1 Hz, 5 Hz, irregular and with missing samples | QA-EVENT-001, QA-EVENT-002, QA-EVENT-003, QA-EVENT-004, QA-EVENT-005, QA-EVENT-006, QA-EVENT-010, QA-EVENT-013, QA-EVENT-014 | **Verified** |
| 39 | EVENT | Edge cases: trip start, trip end (PARTIAL), disappearing fault, manual stop | QA-EVENT-007, QA-EVENT-008, QA-EVENT-009, QA-EVENT-011, QA-E2E-004 | **Verified** |
| 40 | EVENT | Recovery after abrupt close | QA-EVENT-012, QA-E2E-008 | **Verified** |
| 41 | EVENT | Rule detection coverage by condition | QA-EVENT-015 | **Partially Verified** |
| 42 | DB | Schema, pragmas, integrity, foreign keys | QA-DB-001, QA-DB-002, QA-DB-005 | **Verified** |
| 43 | DB | Reports stored and restored, duplicates, reopen | QA-DB-003, QA-DB-004, QA-DB-006 | **Verified** |
| 44 | DB | Old (v1) database upgrade and future-version refusal | QA-DB-007 | **Verified** |
| 45 | DB | Write failure, corrupt file, unavailable path (library and window) | QA-DB-008, QA-DB-009 | **Verified** |
| 46 | DB | Language/theme changes leave stored data untouched | QA-DB-010 | **Verified** |
| 47 | AI | Model facts, trusted loading | QA-AI-001, QA-AI-002 | **Verified** |
| 48 | AI | Determinism, window cases, no future leakage, no label use | QA-AI-003, QA-AI-004, QA-AI-005, QA-AI-006 | **Verified** |
| 49 | AI | ML performance: Rules vs ML vs Combined (window and event level) | QA-AI-010, QA-AI-011, QA-AI-007, QA-AI-008 | **Partially Verified** |
| 50 | XAI | Explanations: deterministic, independent recomputation, safeguards | QA-XAI-001, QA-XAI-002, QA-XAI-003, QA-XAI-004 | **Verified** |
| 51 | AI | AI-to-event linking and AI state reporting | QA-AI-LINK-001, QA-AI-LINK-002, QA-AI-LINK-003, QA-AI-LINK-004, QA-AI-LINK-005, QA-AI-LINK-006 | **Partially Verified** |
| 52 | DIAG | Evidence-based reports for S01..S07 and ambiguity handling | QA-DIAG-S01, QA-DIAG-S02, QA-DIAG-S03, QA-DIAG-S04, QA-DIAG-S05, QA-DIAG-S06, QA-DIAG-S07, QA-DIAG-AMBIG | **Verified** |
| 53 | IOT | Protocol conformance and malformed input | QA-IOT-001, QA-IOT-002, QA-IOT-003, QA-IOT-004, QA-IOT-005, QA-IOT-006, QA-IOT-009, QA-IOT-012 | **Verified** |
| 54 | IOT | Historical event upload, integrity and de-duplication | QA-IOT-007, QA-IOT-008, QA-IOT-010, QA-IOT-011, QA-E2E-007 | **Verified** |
| 55 | IOT | TCP loopback failures: refused, silent, closed, oversized, bad config | QA-IOT-013, QA-IOT-014, QA-IOT-015, QA-IOT-016, QA-IOT-017 | **Verified** |
| 56 | IOT | Serial source with a fake port (never writes) | QA-IOT-018, QA-IOT-019 | **Verified** |
| 57 | IOT | Live loopback device, reconnect and isolation | QA-E2E-006, QA-E2E-010, QA-IOT-020 | **Verified** |
| 58 | PERF | Long run, memory, XAI/ML latency, event persistence | QA-PERF-001, QA-PERF-002, QA-PERF-003, QA-PERF-004 | **Verified** |
| 59 | SEC | Invalid data handling in replay files | QA-SEC-001, QA-SEC-002, QA-SEC-003 | **Partially Verified** |
| 60 | PKG | Wheel, fresh install, installed run, entry point | QA-PKG-001, QA-PKG-002, QA-PKG-003, QA-PKG-004, QA-PKG-005, QA-E2E-012, QA-E2E-012b | **Verified** |
| 61 | FW | Firmware build (ESP-IDF) | QA-FW-001 | **Not Tested** |
| 62 | FW | Firmware static review: target, CAN guard, buffers, test mode, errors | QA-FW-002, QA-FW-004, QA-FW-005, QA-FW-006, QA-FW-007 | **Partially Verified** |
| 63 | FW | Firmware envelope validation (A07) | QA-FW-003 | **Failed** |
| 64 | FW | Hardware: USB, Wi-Fi, CAN, MicroSD, ADC/RTC on a board | QA-FW-008, QA-FW-009, QA-FW-010, QA-FW-011, QA-FW-012 | **Not Tested** |
| 65 | E2E | E2E-01..03, 09: normal, thermal, air/fuel, ML+XAI through the app | QA-E2E-001, QA-E2E-002, QA-E2E-003, QA-E2E-009 | **Verified** |

جرد عناصر الواجهة الفعلية (من النافذة الحية): 10 أزرار، 1 CheckBox، 9 ComboBox، 3 قوائم، 5 SpinBox، 2 DoubleSpinBox، 2 جداول، 3 TextEdit، 11 LineEdit (منها حقول داخلية للـSpinBox)، 0 Slider، 0 قوائم شريطية، 0 اختصارات لوحة مفاتيح — `docs/evidence/full-qa/gate2/ui-inventory.json`.

## 5. مصفوفة تتبع المتطلبات (RTM)

| المتطلب | الاختبارات | PASS | FAIL | PARTIAL | NOT TESTED |
| --- | --- | --- | --- | --- | --- |
| 002 | QA-E2E-006, QA-XAI-001 | 2 | 0 | 0 | 0 |
| 003 | QA-SIM-036 | 1 | 0 | 0 | 0 |
| A07 | QA-FW-003 | 0 | 1 | 0 | 0 |
| AI-002 | QA-AI-004, QA-AI-008 | 2 | 0 | 0 | 0 |
| AI-004 | QA-AI-003, QA-AI-005, QA-AI-006 | 3 | 0 | 0 | 0 |
| AI-005 | QA-E2E-009, QA-E2E-012, QA-UI-008 | 3 | 0 | 0 | 0 |
| AI-007 | QA-AI-001, QA-AI-002, QA-PERF-004 | 3 | 0 | 0 | 0 |
| AI-008 | QA-AI-007, QA-AI-010 | 2 | 0 | 0 | 0 |
| AI-009 | QA-AI-011 | 0 | 1 | 0 | 0 |
| AT-003 | QA-E2E-005 | 1 | 0 | 0 | 0 |
| AT-014 | QA-E2E-008 | 1 | 0 | 0 | 0 |
| AT-MS | QA-DIAG-S01, QA-DIAG-S02, QA-DIAG-S03, QA-DIAG-S04, QA-DIAG-S05, QA-DIAG-S06, QA-DIAG-S07 | 7 | 0 | 0 | 0 |
| AT-MS-01 | QA-E2E-001 | 1 | 0 | 0 | 0 |
| AT-MS-02 | QA-E2E-002 | 1 | 0 | 0 | 0 |
| AT-MS-03 | QA-E2E-003 | 1 | 0 | 0 | 0 |
| AT-MS-06 | QA-E2E-004 | 1 | 0 | 0 | 0 |
| CONN-001 | QA-IOT-013, QA-IOT-015, QA-IOT-016, QA-IOT-019, QA-UI-014, QA-UI-015, QA-UI-040 | 7 | 0 | 0 | 0 |
| DATA-001 | QA-IOT-008, QA-SEC-002, QA-UI-019 | 2 | 1 | 0 | 0 |
| DATA-002 | QA-DB-001, QA-DB-002, QA-DB-003, QA-DB-004, QA-DB-005, QA-DB-006, QA-DB-007, QA-DB-008… | 10 | 0 | 0 | 0 |
| FR-002 | QA-SENSOR-001 | 1 | 0 | 0 | 0 |
| FR-003 | QA-SENSOR-005, QA-SENSOR-006 | 2 | 0 | 0 | 0 |
| FR-004 | QA-IOT-006, QA-IOT-009, QA-SEC-001, QA-SEC-002, QA-SEC-003, QA-SENSOR-002, QA-SENSOR-004 | 6 | 1 | 0 | 0 |
| FR-005 | QA-EVENT-001, QA-EVENT-002, QA-EVENT-003, QA-EVENT-004, QA-EVENT-005, QA-EVENT-006, QA-EVENT-007, QA-EVENT-008… | 13 | 1 | 0 | 0 |
| FR-006 | QA-UI-021 | 1 | 0 | 0 | 0 |
| FR-010 | QA-APP-001, QA-E2E-012b, QA-UI-001, QA-UI-002 | 4 | 0 | 0 | 0 |
| FR-011 | QA-FW-002, QA-FW-008, QA-FW-009, QA-FW-010, QA-FW-011, QA-FW-012 | 0 | 0 | 1 | 5 |
| FR-012 | QA-FW-003, QA-IOT-001, QA-IOT-002, QA-IOT-003, QA-IOT-004, QA-IOT-005, QA-IOT-012, QA-IOT-014… | 8 | 1 | 0 | 0 |
| FR-013 | QA-FW-005, QA-FW-006, QA-FW-007 | 0 | 0 | 3 | 0 |
| INT-002 | QA-DIAG-AMBIG, QA-SIM-038 | 1 | 1 | 0 | 0 |
| INT-003 | QA-AI-LINK-001, QA-AI-LINK-002, QA-AI-LINK-003, QA-AI-LINK-004, QA-AI-LINK-005, QA-AI-LINK-006 | 5 | 0 | 1 | 0 |
| IOT-001 | QA-E2E-006 | 1 | 0 | 0 | 0 |
| IOT-001..003 | QA-UI-041 | 0 | 1 | 0 | 0 |
| IOT-003 | QA-E2E-007, QA-IOT-007, QA-IOT-010, QA-IOT-011 | 4 | 0 | 0 | 0 |
| IOT-004 | QA-E2E-010 | 1 | 0 | 0 | 0 |
| M5 | QA-FW-008, QA-FW-009, QA-FW-010, QA-FW-011, QA-FW-012 | 0 | 0 | 0 | 5 |
| M6 | QA-FW-008, QA-FW-009, QA-FW-010, QA-FW-011, QA-FW-012 | 0 | 0 | 0 | 5 |
| MS-RULE | QA-E2E-005b, QA-EVENT-015, QA-SIM-038 | 1 | 1 | 1 | 0 |
| MS-SIM | QA-SIM-011, QA-SIM-012, QA-SIM-013, QA-SIM-014, QA-SIM-015, QA-SIM-016, QA-SIM-017, QA-SIM-030… | 13 | 0 | 0 | 0 |
| NFR-001 | QA-DB-009, QA-PERF-001, QA-PERF-002, QA-PERF-005, QA-PERF-006, QA-UI-005, QA-UI-006, QA-UI-007… | 11 | 0 | 1 | 0 |
| NFR-002 | QA-E2E-012, QA-E2E-012b, QA-PKG-001, QA-PKG-002, QA-PKG-003, QA-PKG-004, QA-PKG-005 | 7 | 0 | 0 | 0 |
| REPLAY | QA-UI-036, QA-UI-037, QA-UI-038, QA-UI-039 | 3 | 1 | 0 | 0 |
| S01 | QA-DIAG-S01, QA-SIM-011 | 2 | 0 | 0 | 0 |
| S02 | QA-DIAG-S02, QA-SIM-012 | 2 | 0 | 0 | 0 |
| S03 | QA-DIAG-S03, QA-SIM-013 | 2 | 0 | 0 | 0 |
| S04 | QA-DIAG-S04, QA-SIM-014 | 2 | 0 | 0 | 0 |
| S05 | QA-DIAG-S05, QA-SIM-015 | 2 | 0 | 0 | 0 |
| S06 | QA-DIAG-S06, QA-SIM-016, QA-SIM-032 | 3 | 0 | 0 | 0 |
| S07 | QA-DIAG-S07, QA-SIM-017, QA-SIM-031 | 3 | 0 | 0 | 0 |
| SAF-001 | QA-FW-004, QA-IOT-018, QA-IOT-020 | 2 | 0 | 1 | 0 |
| SETTINGS-001 | QA-DB-010, QA-E2E-011, QA-UI-012, QA-UI-013, QA-UI-018, QA-UI-022 | 6 | 0 | 0 | 0 |
| SIM-001 | QA-SIM-002 | 1 | 0 | 0 | 0 |
| SIM-001..003 | QA-UI-004 | 1 | 0 | 0 | 0 |
| SIM-002 | QA-SIM-036 | 1 | 0 | 0 | 0 |
| SIM-003 | QA-SIM-001, QA-SIM-037 | 1 | 1 | 0 | 0 |
| TEST-002 | QA-FW-001 | 0 | 0 | 0 | 1 |
| UI-001 | QA-UI-003, QA-UI-010, QA-UI-016, QA-UI-023, QA-UI-030, QA-UI-031, QA-UI-032, QA-UI-033… | 10 | 0 | 0 | 0 |
| UI-002 | QA-UI-011 | 1 | 0 | 0 | 0 |
| XAI-001 | QA-PERF-003, QA-XAI-001, QA-XAI-003 | 3 | 0 | 0 | 0 |
| XAI-003 | QA-E2E-009, QA-XAI-004 | 2 | 0 | 0 | 0 |
| XAI-004 | QA-XAI-002 | 1 | 0 | 0 | 0 |

## 6. حالات الاختبار (المتوقع والفعلي والدليل)

الإجمالي: 174 حالة مسجلة — المسجَّل: PASS: 152، FAIL: 8، PARTIAL: 8، BLOCKED: 0، NOT TESTED: 6 — بعد التحكيم (فشلان سببهما سكربت QA، انظر adjudication.json): PASS: 152، FAIL: 6، PARTIAL: 9، BLOCKED: 1، NOT TESTED: 6.

| ID | المتطلب | العنوان | المتوقع | الفعلي | الحالة | الدليل |
| --- | --- | --- | --- | --- | --- | --- |
| QA-AI-001 | AI-007 | Model facts recorded: algorithm, version, schema, window, threshold, calibration, runtime versions | IsolationForest, 47-feature schema, 5 s window / 1 s stride, threshold and calibration text present, trained == runtime versions | default=cr005-iforest-v2; v2: IsolationForest x200, uses 25/47 features, threshold=0.5813, policy={'consecutive': 5, 'hysteresis': 0.02}, sklearn 1.9.1 | **PASS** | docs/evidence/full-qa/gate5/model-facts.json |
| QA-AI-002 | AI-007 | Unknown or external model names are refused (no arbitrary joblib loading) | ModelLoadError | ModelLoadError: Unknown model 'no-such-model'; packaged: ('cr004-iforest-v1', 'cr005-iforest-v2') | **PASS** |  |
| QA-AI-003 | AI-004 | Same inputs and a freshly loaded model give bit-identical scores | all scores identical | 156 windows identical=True | **PASS** |  |
| QA-AI-004 | AI-002 | Incomplete, gapped, stale and unsupported windows produce no score; a short sensor loss is reported as coverag | INSUFFICIENT_DATA without score for the four; READY with coverage<1 and finite features for 1 s loss | {"normal (cold, mid-trip)": ["NORMAL", null, 1.0], "incomplete (3 s of data)": ["INSUFFICIENT_DATA", "time/session/sequence_gap", null], "gap in sequence": ["INSUFFICIENT_DATA", "time/session/sequence | **PASS** |  |
| QA-AI-005 | AI-004 | No future leakage: windows ending before the injection are bit-identical to the no-fault trip | all windows ending < 60 s identical; first difference after 60 s | 60 earlier windows identical=True; first differing window ends at 61000 | **PASS** |  |
| QA-AI-006 | AI-004 | Scenario/fault labels in sample metadata do not change the model score | identical scores | scores identical across all windows | **PASS** |  |
| QA-AI-007 | AI-008 | Window-level separability (ROC AUC) of fault windows vs normal windows, per scenario | informational: AUC > 0.5 means the score ranks fault windows higher | S01: v1=0.552 v2=0.704; S02: v1=0.87 v2=0.779; S03: v1=0.891 v2=0.801; S04: v1=0.678 v2=0.784; S05: v1=0.985 v2=0.851; S06: v1=0.574 v2=0.734; S07: v1=0.454 v2=0.733 | **PASS** | docs/evidence/full-qa/gate5/window-auc.json |
| QA-AI-008 | AI-002 | Gradual (S01) and sudden (S05) changes: score trajectory vs threshold | informational | S01 gradual thermal / cr004-iforest-v1: peak 0.623 at 5.0s vs thr 0.565 first-anom 147.0; S01 gradual thermal / cr005-iforest-v2: peak 0.62 at 62.0s vs thr 0.581 first-anom 61.0; S05 sudden voltage /  | **PASS** | docs/evidence/full-qa/gate5/gradual-vs-sudden.json |
| QA-AI-010 | AI-008 | Independent event-level evaluation (never used for training/calibration/selection) | metrics reported honestly; v2 false alarms per hour <= v1; combined not worse than rules on recall | rules 27/28 FA=0; ML v1 13/28 FA=97 (43.3/h); ML v2 5/28 FA=4 (1.79/h); combined v2 27/28 FA=4 | **PASS** | docs/evidence/full-qa/gate5/ml-eval.json |
| QA-AI-011 | AI-009 | Stress: cold-start normal trips with driving scale 1.08-1.15 (known weak region) | no ML false alarm on normal driving | v2 false alarm events=5 in 5/12 trips; v1=32 | **FAIL** | docs/evidence/full-qa/gate5/ml-eval.json |
| QA-AI-LINK-001 | INT-003 | Rule event at 68.2 s links the ML window that ended at 68.0 s (200 ms earlier) | status window_end=68000, age=200 ms, detection=68200; report says rules detected and AI analyzed | detection=68200 window_end=68000 age=200 state=ANALYZED_NORMAL ml_flag=False | **PASS** |  |
| QA-AI-LINK-002 | INT-003 | Linking states: exact/old/none/insufficient; age limit 2000 ms; other session and future windows never linked | state per case as expected; every age/session/future check true | states={'exact (68.0 vs 68.2)': 'ANALYZED_NORMAL', '200 ms older': 'ANALYZED_ANOMALOUS', 'no analysis available': 'NO_RECENT_ANALYSIS', 'insufficient window': 'INSUFFICIENT_DATA'}; checks={'2000 ms ol | **PASS** |  |
| QA-AI-LINK-003 | INT-003 | Session itself does not re-check analysis age (defence in depth) | ideal: Session refuses a stale analysis even if an analyzer implementation returns it | Session linked it: state=ANALYZED_NORMAL links=[('e', 'sess', 60000)]; the age limit is enforced only inside AnomalyAnalyzer.latest_before (verified in QA-AI-LINK-002) | **PARTIAL** |  |
| QA-AI-LINK-004 | INT-003 | AI unavailable cases carry the right state: disabled / model not loaded / inference failed (rules keep working | DISABLED / MODEL_NOT_LOADED / INFERENCE_FAILED and MS_THERMAL still detected | {"disabled": ["DISABLED"], "not loaded": ["MODEL_NOT_LOADED"], "inference failed": ["INFERENCE_FAILED"]} | **PASS** |  |
| QA-AI-LINK-005 | INT-003 | AI detects first, rules confirm later: reported as 'both', with later rule evidence labelled as later | detection_summary combined, text 'AI and rules together', later-evidence sentence present | ML@63000 rules=['MS_AIR_FUEL']@66000 state=ANALYZED_ANOMALOUS | **PASS** |  |
| QA-AI-LINK-006 | INT-003 | A rules-only event is never presented as 'detected by AI' | detection_summary.ml false; text says rules detected | ok | **PASS** |  |
| QA-APP-001 | FR-010 | Native window opens and backend becomes ready | visible window; backend_ready within 15 s | visible=True ready=True platform=windows | **PASS** | docs/evidence/full-qa/gate2/screenshots/01-dashboard-ar-light.png |
| QA-DB-001 | DATA-002 | New database: documented tables, user_version=2, foreign keys ON, WAL, synchronous FULL | all documented tables present; PRAGMAs as documented | tables=['analyses', 'detection_evidence', 'diagnostic_reports', 'event_ai_status', 'event_analyses', 'event_samples', 'events', 'extension_migrations', 'measurements', 'sessions', 'simulation_runs'] u | **PASS** |  |
| QA-DB-002 | DATA-002 | Stored run: integrity ok, no FK violations, measurements and event samples consistent | integrity_check ok; foreign_key_check empty; 776 measurements; no cross-session event samples | integrity=ok fk_violations=0 measurements=776 cross_session=0 | **PASS** |  |
| QA-DB-003 | DATA-002 | Stored reports exist for every finished event and equal a fresh rebuild from the stored event | every finished event has a report; stored == rebuilt | reports=1 finished_events=1 equal=[True] | **PASS** |  |
| QA-DB-004 | DATA-002 | Re-saving the same event does not duplicate; conflicting overwrite of a finalized event is refused | count unchanged; conflict raises | count 1->1; conflict=ValueError: Final event end must match the last sample and follow detection | **PASS** |  |
| QA-DB-005 | DATA-002 | A measurement whose session was never saved is not stored as an orphan | rejected (FK) and no row | result=IntegrityError rows=0 | **PASS** |  |
| QA-DB-006 | DATA-002 | Reopening returns identical events | identical lists | 1 events identical=True | **PASS** |  |
| QA-DB-007 | DATA-002 | Older (v1) database is upgraded in place; a future schema is refused | v1 -> all v2 tables present; 99 -> error | migrated: user_version=2; future: refused: ValueError: Unsupported database version 99 | **PASS** |  |
| QA-DB-008 | DATA-002 | Write failure raises and stores nothing; corrupt, missing-folder and directory paths raise clear errors | all raise; no partial row | write=OperationalError: attempt to write a readonly database; corrupt=DatabaseError: file is not a database; directory=OperationalError: unable to open database file; missing folders: OPENED (the repo | **PASS** |  |
| QA-DB-009 | NFR-001 | The window opened on a corrupt database shows an error and stays alive | window visible; error/status text mentions the storage failure | alive=True message='تعذر فتح التخزين المحلي: file is not a database \| تهيئة التخزين المحلي…' | **PASS** |  |
| QA-DB-010 | SETTINGS-001 | Changing language/theme does not change stored sessions, measurements, events or reports | logical content hash identical | before=64722af82a57a91b after=64722af82a57a91b | **PASS** |  |
| QA-DIAG-AMBIG | INT-002 | Confusable air/fuel/airflow patterns: reports must not pretend to separate causes the evidence cannot separate | different evidence -> different hypothesis sets; shared hypotheses declared as shared; no definitive single cause | hypothesis sets: {"S02": ["Possible air measurement bias or fuel limitation", "Possible unmetered intake air"], "S03": ["Possible fuel supply limitation", "Possible intake leak or measurement bias"],  | **PASS** | docs/evidence/full-qa/gate6/diagnostic-review.json |
| QA-DIAG-S01 | AT-MS/S01 | S01: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S01-ar.txt |
| QA-DIAG-S02 | AT-MS/S02 | S02: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S02-ar.txt |
| QA-DIAG-S03 | AT-MS/S03 | S03: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S03-ar.txt |
| QA-DIAG-S04 | AT-MS/S04 | S04: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S04-ar.txt |
| QA-DIAG-S05 | AT-MS/S05 | S05: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S05-ar.txt |
| QA-DIAG-S06 | AT-MS/S06 | S06: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S06-ar.txt |
| QA-DIAG-S07 | AT-MS/S07 | S07: report is evidence-based, numerically correct, hedged and free of injected-fault names | >=2 hypotheses (alternatives), contradiction/missing-evidence fields, checks, measurements equal stored values, no scenario/ground-truth wording, no d | hyp=2 contra_field=True missing=True checks=True values_ok=True/True leaks=[] definitive=[] disclaimers=True | **PASS** | docs/evidence/full-qa/gate6/reports/S07-ar.txt |
| QA-E2E-001 | AT-MS-01 | Normal trip from the app: start, readings, ML on, finish; no unjustified alarms (4 seeds, default scale) | 776 samples each and zero events | [{"seed": 42, "samples": 776, "events": [], "finished": true}, {"seed": 777, "samples": 776, "events": [], "finished": true}, {"seed": 2026, "samples": 776, "events": [], "finished": true}, {"seed": 4 | **PASS** | docs/evidence/full-qa/gate10/e2e01.json |
| QA-E2E-002 | AT-MS-02 | Thermal rise through the app: detection, saved event, report with checks | MS_THERMAL event COMPLETE; report lists cooling check; AI state stated; hedged | events=[('MS_THERMAL', 68.2, 'COMPLETE')]; chars=1597 | **PASS** | docs/evidence/full-qa/gate10/e2e02-thermal-S01-simple-ar.txt |
| QA-E2E-003 | AT-MS-03 | Air/fuel disturbance through the app: pattern detected, MAF/MAP evidence, readable report | MS_AIR_FUEL event; technical report shows MAF and MAP residuals; simple report hedged | events=[('MS_AIR_FUEL', 66.0, 'COMPLETE')] | **PASS** | docs/evidence/full-qa/gate10/e2e03-airfuel-S02-technical.txt |
| QA-E2E-004 | AT-MS-06 | Intermittent fault: it appears and disappears but recording continues to T+30 and the event is saved | MS_COMBUSTION COMPLETE with samples from T-30 to T+30 | event=('456f4eea-3a7c-506e-b272-8534f7cf5886', 'MS_COMBUSTION', 68000, 'COMPLETE'); samples 38000..98000 n=301 | **PASS** |  |
| QA-E2E-005 | AT-003 | RANDOM_FAULTS through the app: 30 s cycles recorded as separate ground truth and compared with detections | cycle schedule stored in simulation_runs; every injected instance listed with detected yes/no | cycles=5 injected=7 detected=2/7; events=[('ML_ANOMALY', 64.0), ('DATA_QUALITY', 90.0), ('MS_SIGNAL', 90.0), ('MS_AIRFLOW', 96.2), ('DATA_QUALITY', 124.0)] | **PASS** | docs/evidence/full-qa/gate10/e2e05.json |
| QA-E2E-005b | MS-RULE | Every missed injection in the app's RANDOM_FAULTS run has an identified cause | no 'unexplained' miss | S01@30s/5s: 5 s thermal fault too short for the rule (needs sustained rise); S04@60s/18s: masked by the simultaneous S07 flatline (QA-SIM-038); S07@60s/18s: flatline variant is a known undetected patt | **PASS** | docs/evidence/full-qa/gate10b/random-run-misses.json |
| QA-E2E-006 | IOT-001/002 | Live loopback device: handshake, 776 samples, live event detected and stored, device info labelled as software | 776 accepted; >=1 live non-quality event; info.vehicle_verified false; transport TCP_LOOPBACK | {"accepted": 776, "historical": 2, "live": ["MS_AIR_FUEL"], "sessions": [61, 776, 61], "info": {"state": "DISCONNECTED", "device_id": "doctorcar-loopback-simulator", "session_id": "c15c136e-7476-4f1b- | **PASS** |  |
| QA-E2E-007 | IOT-003 | Device memory: 2 historical events imported once; reconnecting later does not duplicate them | 2 HISTORICAL events after both runs (not 4) | first run historical=2; second run total historical=2 | **PASS** |  |
| QA-E2E-008 | AT-014 | Restart: events and reports are restored identically and sessions are not mixed | same number of events, identical report text, one session | events 1->1; report identical=True; sessions=1 | **PASS** | docs/evidence/full-qa/gate10/screenshots/e2e08-restored-report.png |
| QA-E2E-009 | AI-005/XAI-003 | ML + XAI with the real model through the app: an event whose AI result is anomalous shows computed XAI factors | AI state in the report; if anomalous, factors line + 'not mechanical causes'; technical report lists XAI method and model version | xai_in_simple=True; model_in_technical=True; ai_label=AI: نشط — نمط معتاد \| 0.527 \| iforest-cr005-v2 | **PASS** | docs/evidence/full-qa/gate10/e2e09-supply-S05-technical.txt |
| QA-E2E-010 | IOT-004 | Connection loss and reconnect: RECONNECTING shown, new boot isolated, no mixed sessions | RECONNECTING observed; reconnects==1; live samples split into two sessions of 51; historical events once | states=['HANDSHAKE_PENDING', 'RECEIVING_DATA', 'RECONNECTING', 'RUNNING', 'RECEIVING_DATA'] reconnects=1 per-session sample counts=[51, 51, 61, 61] historical=2 | **PASS** |  |
| QA-E2E-011 | SETTINGS-001 | Language/theme change, restart, old report rendered in English; stored data unchanged | settings persisted; English report text; database logical hash unchanged | persisted=('en', 'dark'); english_report_ok=True; same_after_restart=True; db_hash_unchanged=True | **PASS** | docs/evidence/full-qa/gate10/screenshots/e2e11-en-dark-report.png |
| QA-E2E-012 | NFR-002/AI-005 | Fresh install: simulation with ML and XAI, new database, report with AI section | 776 accepted, XAI-bearing event, report includes the AI section | {"accepted": 776, "events": [["ML_ANOMALY", "COMPLETE"], ["ML_ANOMALY", "COMPLETE"]], "xai_event": "ML_ANOMALY", "report_chars": 2441, "report_has_ai_section": true} | **PASS** | docs/evidence/full-qa/gate9/installed-e2e.json |
| QA-E2E-012b | NFR-002/FR-010 | Fresh install: native GUI starts, runs a faulty simulation with AI, shows an event, opens the report and close | backend ready, event complete, report opened, worker finished | {"gui_platform": "windows", "gui_backend_ready": true, "gui_event_complete": true, "gui_ai_label": "AI: نشط — نمط معتاد \| 0.515 \| iforest-cr005-v2", "gui_report_opened": true, "gui_report_chars": 16 | **PASS** | docs/evidence/full-qa/gate9/screenshots/installed-app-report.png |
| QA-EVENT-001 | FR-005 | Recording window: mid-5Hz | no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples | events=1; MS_THERMAL@68.2s n=301 exp~301 COMPLETE first=38.2 last=98.2 | **PASS** |  |
| QA-EVENT-002 | FR-005 | Recording window: mid-1Hz | no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples | events=1; MS_THERMAL@69.0s n=61 exp~61 COMPLETE first=39.0 last=99.0 | **PASS** |  |
| QA-EVENT-003 | FR-005 | Recording window: start-5Hz | no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples | events=2; MS_SIGNAL@8.6s n=194 exp~194 COMPLETE first=0.0 last=38.6 | **PASS** |  |
| QA-EVENT-004 | FR-005 | Recording window: near-end-5Hz | no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples | events=2; MS_SUPPLY@136.0s n=246 exp~246 PARTIAL first=106.0 last=155.0 | **PASS** |  |
| QA-EVENT-005 | FR-005 | Recording window: disappearing-5s | no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples | events=3; MS_COMBUSTION@90.0s n=301 exp~301 COMPLETE first=60.0 last=120.0; MS_SUPPLY@61.0s n=301 exp~301 COMPLETE first=31.0 last=91.0 | **PASS** |  |
| QA-EVENT-006 | FR-005 | Recording window: long-90s | no sample outside [T-30,T+30]; COMPLETE only when covered; PARTIAL/limitation explained; ordered samples | events=2; MS_THERMAL@113.0s n=301 exp~301 COMPLETE first=83.0 last=143.0; MS_THERMAL@46.6s n=301 exp~301 COMPLETE first=16.6 last=76.6 | **PASS** |  |
| QA-EVENT-007 | FR-005 | Event detected near the end of the trip is PARTIAL with an explicit reason | status PARTIAL and a limitation text; last sample = trip end | [["MS_SUPPLY", "PARTIAL", 155000, ["توقف المصدر قبل اكتمال 30 ثانية بعد الحدث"]]] | **PASS** |  |
| QA-EVENT-008 | FR-005 | Event at trip start keeps the available pre-window and states it is shorter | first sample = 0 and a limitation 'shorter than 30 s' | first=0 limitations=['نافذة ما قبل الحدث أقصر من 30 ثانية؛ حُفظت البيانات المتاحة فقط'] | **PASS** |  |
| QA-EVENT-009 | FR-005 | A fault that disappears after 5 s does not cancel the event (recording continues to T+30) | event exists and last sample >= detection + 29 s | [["MS_COMBUSTION", 90000, 120000], ["MS_SUPPLY", 61000, 91000]] | **PASS** |  |
| QA-EVENT-010 | FR-005 | Overlapping events: each keeps its own full window; shared samples stored once | >=2 distinct non-quality events, windows overlap, samples shared via event_samples (not duplicated in measurements) | kinds=['MS_AIR_FUEL', 'MS_THERMAL']; overlapping=True; shared sample rows=204 | **PASS** | docs/evidence/full-qa/gate4/event-windows.json |
| QA-EVENT-011 | FR-005 | Manual stop during recording finalizes the event as PARTIAL with the reason | PARTIAL, last sample ~80 s, reason recorded | [('MS_THERMAL', 'PARTIAL', 80000, ['توقف المصدر قبل اكتمال 30 ثانية بعد الحدث'])] | **PASS** |  |
| QA-EVENT-012 | DATA-002 | Abrupt close during recording: the event is recovered as PARTIAL on reopen with its checkpoint samples | status RECORDING before reopen; PARTIAL after with samples up to the last checkpoint; session marked interrupted | before=['RECORDING'] after=PARTIAL samples=210 last=80000 limitations=['استُعيد تسجيل غير مكتمل بعد توقف سابق؛ البيانات بعد الحدث جزئية'] sessions=[<sqlite3.Row object at 0x0000021C4370BDC0>] | **PASS** |  |
| QA-EVENT-013 | FR-005 | Irregular arrival rate (100-400 ms): windows follow sample time, not row count | no sample outside the time window; ordered; coverage by time | MS_THERMAL@90.1s n=232 first=60.4 last=119.9 COMPLETE | **PASS** |  |
| QA-EVENT-014 | FR-005 | 20% missing samples: window bounds hold and missing intervals are measurable, not invented | no sample outside [T-30,T+30]; no synthetic samples (count <= nominal) | DATA_QUALITY@162.2s n=187 gaps=68 COMPLETE; DATA_QUALITY@130.9s n=187 gaps=67 COMPLETE; DATA_QUALITY@98.3s n=199 gaps=71 COMPLETE; MS_THERMAL@85.8s n=183 gaps=74 COMPLETE | **PASS** |  |
| QA-EVENT-015 | MS-RULE | Rule detection coverage by start time and duration (35 combinations, rules only, severity 1.0) | informational: every injected fault should either produce an event or be listed as a coverage gap | 25/35 produced a non-quality event; NOT detected: S01@60s/5s, S02@60s/5s, S02@110s/35s, S02@135s/15s, S03@60s/5s, S03@110s/35s, S03@135s/15s, S04@60s/5s, S04@110s/35s, S04@135s/15s | **PARTIAL** | docs/evidence/full-qa/gate4/detection-coverage.json |
| QA-EVENT-016 | FR-005 | A second fault of the same kind starting right after the first event's T+30 boundary gets its own event | each of the two faults produces its own MS_SIGNAL event | {"S07 dropout at 90 s and again at 120.0 s": 1, "S07 dropout at 90 s and again at 120.2 s": 2, "S07 dropout at 90 s and again at 121.0 s": 2, "S07 dropout at 90 s and again at 125.0 s": 2} | **FAIL** | docs/evidence/full-qa/gate10b/same-kind-boundary.json |
| QA-FW-001 | TEST-002 | Firmware build (ESP-IDF 5.5.x, esp32s3) | build succeeds without flashing | FIRMWARE BUILD — NOT TESTED: tools not found {'idf.py': None, 'cmake': None, 'ninja': None, 'gcc': None, 'clang': None, 'xtensa-esp32s3-elf-gcc': None}; IDF_PATH unset | **NOT TESTED** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-002 | FR-011 | Target and SDK guards in CMake/sdkconfig/C | ESP32-S3 only and IDF >= 5.5 enforced at configure/compile time | {"cmake_fatal_unless_esp32s3": true, "sdkconfig_target": true, "c_error_unless_s3": true, "c_error_below_idf_5_5": true} | **PARTIAL** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-003 | FR-012/A07 | A07: C receiver validates only part of the mandatory envelope (static reproduction) | all 8 mandatory fields validated before acting (as the Python decoder does) | validated: ['protocol_version', 'type']; NOT validated: ['device_id', 'session_id', 'sequence_number', 'timestamp_ms', 'source', 'payload']. A HELLO such as {"protocol_version":1,"type":"HELLO"} reach | **FAIL** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-004 | SAF-001 | Real CAN is disabled and guarded; Wi-Fi/MicroSD/ADC/RTC are not implemented | CAN guard present; no TWAI/Wi-Fi/SD/ADC/RTC usage | {"real_can_flag_zero": true, "compile_error_if_enabled": true, "twai_used": false, "wifi_used": false, "sd_used": false, "adc_used": false, "rtc_used": false} | **PARTIAL** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-005 | FR-013 | Line-size limit is consistent between C (4096) and Python (4096 incl. LF); oversize is discarded with an ERROR | same limit; overflow discards until LF and sends OVERSIZED_MESSAGE | {"DC_MAX_LINE": ["main/device_protocol.h:7: #define DC_MAX_LINE 4096"], "input_buffer": ["main/device_protocol.c:11: static char input[DC_MAX_LINE];"], "overflow_guard": ["main/device_protocol.c:133:  | **PARTIAL** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-006 | FR-013 | Test mode: data labelled DEVICE_TEST, event upload not advertised | DEVICE_TEST label and event_upload=false | {"source_DEVICE_TEST": true, "event_upload_false": true, "test_data_kconfig": true} | **PARTIAL** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-007 | FR-013 | Error behaviour in the C receiver | INVALID_MESSAGE / UNSUPPORTED_MESSAGE / OVERSIZED_MESSAGE exist; no vehicle-changing command | main/device_protocol.c:113: send_error("INVALID_MESSAGE", ms);; main/device_protocol.c:117: send_error("UNSUPPORTED_MESSAGE", ms);; main/device_protocol.c:128: if (discarding) send_error("OVERSIZED_ME | **PARTIAL** | docs/evidence/full-qa/gate9/firmware-static-review.json |
| QA-FW-008 | FR-011/M5/M6 | USB Serial/JTAG on a physical ESP32-S3 | hardware test | NOT TESTED: no board connected; no COM port opened | **NOT TESTED** |  |
| QA-FW-009 | FR-011/M5/M6 | Wi-Fi on ESP32 | hardware test | NOT TESTED: no board, no toolchain, feature not implemented in M1 | **NOT TESTED** |  |
| QA-FW-010 | FR-011/M5/M6 | CAN (TWAI) | hardware test | NOT TESTED: no board, no toolchain, feature not implemented in M1 | **NOT TESTED** |  |
| QA-FW-011 | FR-011/M5/M6 | MicroSD | hardware test | NOT TESTED: no board, no toolchain, feature not implemented in M1 | **NOT TESTED** |  |
| QA-FW-012 | FR-011/M5/M6 | ADC / RTC / vehicle power | hardware test | NOT TESTED: no board, no toolchain, feature not implemented in M1 | **NOT TESTED** |  |
| QA-IOT-001 | FR-012 | Valid HELLO + CAPABILITIES + samples are accepted | samples queued, no errors, sensors advertised | samples=10 errors=[] sensors=12 | **PASS** |  |
| QA-IOT-002 | FR-012 | Python parser rejects an incomplete HELLO envelope (the case A07 says the C firmware accepts) | error recorded, no handshake | errors=['Invalid protocol message: ValidationError'] identity=None | **PASS** |  |
| QA-IOT-003 | FR-012 | Malformed protocol input is rejected without crashing the receiver | each produces an error or no state | {"version 2": [true, ["Unsupported protocol version"]], "version true": [true, ["Unsupported protocol version"]], "invalid JSON": [true, ["Expecting property name enclosed in double quotes: line 1 col | **PASS** |  |
| QA-IOT-004 | FR-012 | A very large line is dropped and the stream recovers on the next valid message | oversized error then the sample is accepted | errors=['oversized_line'] samples=1 | **PASS** |  |
| QA-IOT-005 | FR-012 | Duplicate sequence is suppressed (one sample), a skipped sequence is counted but data kept | 1 sample for the duplicate; sequence_gaps==1 for the gap | duplicate samples=1 errors=[]; gap: gaps=1 samples=2 | **PASS** |  |
| QA-IOT-006 | FR-004 | Unknown sensor and boolean reading in a SAMPLE are rejected | error and no sample queued | {"unknown sensor": [["Unadvertised sensor"], 0], "boolean value": [["Invalid protocol message: ValidationError"], 0]} | **PASS** |  |
| QA-IOT-007 | IOT-003 | Historical event upload: valid assembly; missing chunk and wrong hash are not stored as events | valid -> 2 events (expected 2); missing chunk -> fewer; bad hash -> fewer + error | valid=2 dropped_messages=1 missing_chunk=1 (errors ['Incomplete event upload']) bad_hash=1 (errors ['Event integrity failure']) sent twice=2 (DB de-duplicates, see QA-IOT-011) | **PASS** |  |
| QA-IOT-008 | DATA-001 | Invalid event window (end before detection) is refused | ValueError | ValueError: Final event end must match the last sample and follow detection | **PASS** |  |
| QA-IOT-009 | FR-004 | Backward timestamp in a device stream is rejected by quality validation (counted, not stored) | rejected >= 1, accepted 4 | {"error": null, "accepted": 4, "rejected": 1, "events": 1, "measurements": 4} | **PASS** |  |
| QA-IOT-010 | IOT-003 | A protocol file that ends in the middle of an event upload is reported, no partial event stored | error 'Truncated' and 0 events | {"error": "ValueError: Truncated protocol stream/event", "accepted": 0, "rejected": 0, "events": 0, "measurements": 0} | **PASS** |  |
| QA-IOT-011 | IOT-003 | The same historical upload received in two separate connections stores each event once; replaying identical se | 2 events after the second connection; same-stream replay raises a protocol error | {"two_connections": {"error": null, "accepted": 156, "rejected": 0, "events": 2, "measurements": 278}, "same_stream_replay": {"error": "ValueError: خطأ بروتوكول الجهاز: HELLO is required for this devi | **PASS** |  |
| QA-IOT-012 | FR-012 | Corrupted line in a protocol file ends with a clear protocol error | error reported | {"error": "ValueError: خطأ بروتوكول الجهاز: Expecting value: line 1 column 1 (char 0)", "accepted": 0, "rejected": 0, "events": 0, "measurements": 0} | **PASS** |  |
| QA-IOT-013 | CONN-001 | Closed port raises an OSError (refused/timeout); LAN/hostname/IPv6/invalid port/timeout/reconnect configs are  | refused -> OSError; invalid -> ValueError | closed port -> TimeoutError; {'LAN host': 'rejected', 'hostname': 'rejected', 'ipv6': 'rejected', 'port 0': 'rejected', 'port 70000': 'rejected', 'timeout 0': 'rejected', 'reconnects 9': 'rejected', ' | **PASS** |  |
| QA-IOT-014 | FR-012 | Garbage after the handshake over TCP raises a protocol error to the application | ValueError (protocol error) | error=ValueError('خطأ بروتوكول الجهاز: Invalid protocol message: UnicodeDecodeError') samples=0 state=RECEIVING_DATA | **PASS** |  |
| QA-IOT-015 | CONN-001 | A server that accepts but never sends: timeout leads to CONNECTION_LOST (no hang) | ConnectionError within ~1 s | error=ConnectionError('TCP reconnect budget exhausted') state=CONNECTION_LOST after 0.31s | **PASS** |  |
| QA-IOT-016 | CONN-001 | Server closes the stream mid-data: samples already received are delivered, then CONNECTION_LOST | some samples, then ConnectionError, state CONNECTION_LOST | samples=5 error=ConnectionError('TCP reconnect budget exhausted') state=CONNECTION_LOST | **PASS** |  |
| QA-IOT-017 | FR-012 | A 200 KB line without newline over TCP is rejected (bounded memory) | protocol error, receiver buffer bounded | error=ValueError('خطأ بروتوكول الجهاز: oversized_line') pending_bytes=0 | **PASS** |  |
| QA-IOT-018 | SAF-001 | Serial (fake port): valid stream decoded; the app never writes to the port; unplug and garbage are reported; e | samples decoded, writes==0, ConnectionError on unplug, ValueError on garbage, port closed | decoded=3 writes=0 unplug=ConnectionError('USB serial connection lost') garbage=ValueError('خطأ بروتوكول الجهاز: Expecting value: line 1 column 1 (char 0)') empty=rejected url=rejected | **PASS** |  |
| QA-IOT-019 | CONN-001 | No handshake within the documented 10 s raises TimeoutError and state TIMEOUT | TimeoutError | TimeoutError('لم تكتمل مصافحة الجهاز خلال 10 ثوانٍ') | **PASS** |  |
| QA-IOT-020 | SAF-001 | Connecting to a loopback simulator is not evidence of a vehicle connection | vehicle_verified false, transport TCP_LOOPBACK | vehicle_verified=False transport=TCP_LOOPBACK | **PASS** | docs/evidence/full-qa/gate7/iot-details.json |
| QA-PERF-001 | NFR-001 | Long run: 12 consecutive RANDOM_FAULTS trips (1860 simulated s, 30 s cycles) with AI on; nothing dropped, inte | all samples accepted, none rejected, integrity ok, realtime factor > 5 | {"trips": 12, "simulated_seconds": 1860, "samples_generated": 9324, "samples_accepted": 9312, "samples_rejected": 0, "expected_samples": 9312, "wall_s": 72.9, "cpu_s": 38.5, "throughput_samples_per_s" | **PASS** | docs/evidence/full-qa/gate8/long-run.json |
| QA-PERF-002 | NFR-001 | Memory does not grow without bound across 12 sessions (process working set) | growth after the first trip < 150 MB | after trip 1: 291.6 MB; end: 296.9 MB; growth 5.3 MB | **PASS** | docs/evidence/full-qa/gate8/long-run.json |
| QA-PERF-003 | XAI-001 | Repeated XAI explanations (200x) are fast and stable | p95 < 500 ms (analysis cadence is 1 s) | {"xai_ms_median": 26.82, "xai_ms_p95": 28.01, "xai_ms_max": 30.04} | **PASS** |  |
| QA-PERF-004 | AI-007 | Model load time | < 2 s each | 21 ms per load | **PASS** |  |
| QA-PERF-005 | NFR-001 | Project-defined performance limits | tests against defined limits | The control file defines no numeric latency/throughput requirements (only non-blocking GUI, bounded queue 32, 120 ms UI refresh); results above are measurements, not pass/fail against a spec | **PARTIAL** | docs/evidence/full-qa/gate8/long-run.json |
| QA-PERF-006 | NFR-001 | GUI stays responsive while 30x RANDOM_FAULTS + AI run, pages are switched and reports opened | no event-loop gap > 1 s; no error shown; reports produced | {"page_switches": 157, "reports_requested": 22, "event_rows": 3, "max_gui_gap_s": 0.084, "p99_gap_s": 0.052, "errors_shown": [], "memory_mb": [384.2, 403.8]} | **PASS** | docs/evidence/full-qa/gate8/gui-stress.json |
| QA-PKG-001 | NFR-002 | Wheel builds from the current sources | a doctorcar-0.1.0 wheel is produced | exit=0 wheel=doctorcar-0.1.0-py3-none-any.whl size=1162139 | **PASS** |  |
| QA-PKG-002 | NFR-002 | Wheel contains both models, metadata and the protocol schema; no tests, data or firmware leak in | required resources present; no tests/audits/data/firmware entries | files=59 missing=[] unexpected=[] | **PASS** |  |
| QA-PKG-003 | NFR-002 | Fresh virtual environment: install with [ml] extra and the lock file; pip check clean | install exit 0; no broken requirements | install_exit=0 (59s) pip_check='No broken requirements found.' [notice] To update, run: C:\Users\user\AppData\Local\Temp\claude\C--doccar\d8a9af6d-01f7-4fb1-be56-5ec89ed33b45\scratchpad\doctorcar-qa\ | **PASS** | docs/evidence/full-qa/gate9/qa-venv-pip-list.txt |
| QA-PKG-004 | NFR-002 | Installed package runs from site-packages, finds its models and schema, and does not depend on the development | package and models under site-packages; dev tree not on sys.path; no absolute dev paths in installed sources; schema resource present | {"package_file": "C:\\Users\\user\\AppData\\Local\\Temp\\claude\\C--doccar\\d8a9af6d-01f7-4fb1-be56-5ec89ed33b45\\scratchpad\\doctorcar-qa\\package\\qa-venv\\Lib\\site-packages\\doctorcar\\__init__.p | **PASS** | docs/evidence/full-qa/gate9/installed-e2e.json |
| QA-PKG-005 | NFR-002 | Console entry point works and both models load in the installed environment | exit 0 and versions reported | help_exit=0 loaded=['iforest-cr004-v1', 'iforest-cr005-v2'] | **PASS** | docs/evidence/full-qa/gate9/installed-e2e.json |
| QA-SEC-001 | FR-004 | Invalid data in a replay file is rejected with an error (NaN, Infinity, bool, string, missing field, backward  | valid accepted; every mutation rejected (no crash) | {"valid": "ACCEPTED", "NaN value": "rejected: ValueError: reading must be a finite number or null", "Infinity value": "rejected: ValueError: reading must be a finite number or null", "boolean value":  | **PASS** | docs/evidence/full-qa/gate8/negative-data.json |
| QA-SEC-002 | FR-004/DATA-001 | A finite but physically absurd reading (RPM = 1e308) in a REPLAY file is not stored as AVAILABLE | flagged INVALID (or rejected) and a data-quality event | stored RPM value=1e+308 quality=AVAILABLE; events=[] | **FAIL** | docs/evidence/full-qa/gate8/negative-data.json |
| QA-SEC-003 | FR-004 | An unknown sensor id in a replay file is flagged (UNSUPPORTED + data-quality event), not silently accepted | quality UNSUPPORTED and DATA_QUALITY event | FOO stored={'quality': 'UNSUPPORTED', 'unit': 'x', 'value': 1}; events=['DATA_QUALITY'] | **PASS** | docs/evidence/full-qa/gate8/negative-data.json |
| QA-SENSOR-001 | FR-002 | Registry has the 11 documented numeric sensors with documented units + DTC | ids and units equal the control-file table (G) | 12 sensors; unit mismatches: none | **PASS** |  |
| QA-SENSOR-002 | FR-004 | Every sample of a normal 155 s trip: finite numeric values, correct units, AVAILABLE | 776 samples, step 200 ms, contiguous sequence, no bad type/unit/quality | samples=776 steps=[200] seq_contiguous=True bad_type=0 bad_unit=0 bad_quality=0 | **PASS** |  |
| QA-SENSOR-003 | DATA-002 | Simulation output -> validated sample -> Session -> SQLite is value-exact for all samples | 0 mismatches, max \|difference\| = 0 (no rounding applied by the pipeline) | rows=776 session_vs_db_mismatches=0 max_diff=0.0 source_vs_db_mismatches=0 | **PASS** |  |
| QA-SENSOR-004 | FR-004 | Validator: missing/unsupported/unit/range/stale/duplicate/backward timestamps | MISSING and UNSUPPORTED stay explicit (never 0 or AVAILABLE); wrong unit and out-of-range flagged; stale flagged; duplicate and backward rejected; NaN | {"dup_accepted": false, "backward_accepted": false, "missing": {"MAF": "MISSING"}, "unsupported": {"MAF": "UNSUPPORTED"}, "wrong_unit": {"COOLANT_TEMP": "INVALID"}, "implausible_rpm": {"RPM": "INVALID | **PASS** |  |
| QA-SENSOR-005 | FR-003 | Declared relations hold in every sample of 4 normal trips (cold/warm/scale 0.86/1.14) | 0 violations over 4 x 776 samples | violations {"maf": 0, "map": 0, "volt": 0, "load": 0, "coolant": 0}; coolant start cold=22.0 warm=85.0 | **PASS** | docs/evidence/full-qa/gate3/operating-phase-statistics.json |
| QA-SENSOR-006 | FR-003 | Plausible couplings: throttle~load, speed~rpm in acceleration, load~MAF, idle rpm, trims bounded | corr(throttle,load)>0.9; corr(speed,rpm \| accel)>0.99; corr(load,MAF)>0.9; idle rpm 800-820; \|STFT\|<=2; LTFT 1.2-1.8 | corr_thr_load=0.990 corr_speed_rpm_accel=0.9999 corr_load_maf=0.920 idle_rpm=811.5 stft=[-2.00,2.00] ltft=[1.500,1.800] | **PASS** |  |
| QA-SIM-001 | SIM-003 | Same seed reproduces all readings; different seed changes noisy signals | identical for same seed; RPM differs in >50% samples for another seed | identical=True rpm_differs_other_seed=725/776 | **PASS** |  |
| QA-SIM-002 | SIM-001 | Trip length follows duration (0..60 s at 200 ms = 301 samples; no gaps) | 301 samples | 301 samples | **PASS** |  |
| QA-SIM-011 | MS-SIM/S01 | S01: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['COOLANT_TEMP', 'INTAKE_TEMP'] changed=['COOLANT_TEMP', 'INTAKE_TEMP'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-012 | MS-SIM/S02 | S02: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['ENGINE_LOAD', 'INTAKE_PRESSURE', 'LONG_FUEL_TRIM', 'MAF', 'RPM', 'SHORT_FUEL_TRIM'] changed=['ENGINE_LOAD', 'INTAKE_PRESSURE', 'LONG_FUEL_TRIM', 'MAF', 'RPM', 'SHORT_FUEL_TRIM'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-013 | MS-SIM/S03 | S03: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['ENGINE_LOAD', 'INTAKE_PRESSURE', 'LONG_FUEL_TRIM', 'MAF', 'RPM', 'SHORT_FUEL_TRIM'] changed=['ENGINE_LOAD', 'INTAKE_PRESSURE', 'LONG_FUEL_TRIM', 'MAF', 'RPM', 'SHORT_FUEL_TRIM'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-014 | MS-SIM/S04 | S04: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['INTAKE_TEMP', 'MAF'] changed=['INTAKE_TEMP', 'MAF'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-015 | MS-SIM/S05 | S05: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['CONTROL_MODULE_VOLTAGE', 'MAF', 'RPM'] changed=['CONTROL_MODULE_VOLTAGE', 'MAF', 'RPM'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-016 | MS-SIM/S06 | S06: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['ENGINE_LOAD', 'INTAKE_PRESSURE', 'MAF', 'RPM', 'SHORT_FUEL_TRIM'] changed=['ENGINE_LOAD', 'INTAKE_PRESSURE', 'MAF', 'RPM', 'SHORT_FUEL_TRIM'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-017 | MS-SIM/S07 | S07: only declared sensors change, and only inside the injection window | changed sensors subset of declared writes; nothing changed outside [60,95) s | declared=['INTAKE_PRESSURE'] changed=['INTAKE_PRESSURE'] outside=0 | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-030 | MS-SIM | Direction of the effect matches each scenario's definition | S01 coolant up; S02 MAF down; S03 short trim up; S04 MAF biased; S05 voltage down | {"S01 coolant rises >10 C": [true, {"n": 174, "max_abs": 38.028, "mean_delta": 29.811}], "S02 MAF lower than baseline": [true, {"n": 174, "max_abs": 2.796, "mean_delta": -2.112}], "S03 short trim posi | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-031 | MS-SIM/S07 | S07 variants: dropout -> MISSING readings; implausible -> INVALID/out-of-range; flatline -> constant value | dropout and implausible raise non-AVAILABLE readings or change values; flatline freezes a sensor | dropout non-available=45 implausible non-available=45 flatline affected=['INTAKE_PRESSURE'] | **PASS** | docs/evidence/full-qa/gate3/fault-effects.json |
| QA-SIM-032 | MS-SIM/S06 | S06 is intermittent: several separate pulses with normal samples between them | >=2 separate pulses inside the window, no changes outside | pulses=6 first=60000 last=92800 | **PASS** |  |
| QA-SIM-033 | MS-SIM | Injection of 5 s is applied for its duration and then recovers | first change >= 60 s; changes stop within one second after the end | changed from 60200 to 64800 | **PASS** |  |
| QA-SIM-034 | MS-SIM | Injection of 90 s is applied for its duration and then recovers | first change >= 60 s; changes stop within one second after the end | changed from 60200 to 144800 | **PASS** |  |
| QA-SIM-035 | MS-SIM | Simultaneous scenarios combine; conflicting writes to the same sensor are rejected | union of effects for compatible; error for conflicts; three-scenario behaviour reported | S01+S02 changed=['COOLANT_TEMP', 'ENGINE_LOAD', 'INTAKE_PRESSURE', 'INTAKE_TEMP', 'LONG_FUEL_TRIM', 'MAF', 'RPM', 'SHORT_FUEL_TRIM']; same-scenario overlap rejected: Conflicting scenario writes: S01,  | **PASS** |  |
| QA-SIM-036 | SIM-002/003 | RANDOM_FAULTS: 30 s cycles, ground-truth schedule recorded, same seed reproducible, other seed differs | cycles recorded every 30 s; identical schedule and data for the same seed; different schedule for another seed | cycles=5 schedule_repeat=True data_repeat=True other_seed_differs=True | **PASS** | docs/evidence/full-qa/gate3/random-faults-metadata.json |
| QA-SIM-037 | SIM-003 | A simulation longer than the 155 s driving profile keeps producing driving data and periodic fault effects | engine keeps running (RPM > 0) so cycles every 30 s remain meaningful | after 150 s: 2250 samples, max RPM=0.0 (engine stays off); 19 fault cycles are still scheduled up to 600 s | **FAIL** | docs/evidence/full-qa/gate8/long-run.json |
| QA-SIM-038 | MS-RULE/INT-002 | A detectable fault stays detectable when a second, simultaneous fault is present | S04 is still detected in the combination | {"S04 alone": [["MS_AIRFLOW", 66.2]], "S07 flatline alone": [], "S04 + S07 flatline together": [], "S04 + S07 dropout (5 s at 120 s) together": [["MS_SIGNAL", 120.0], ["MS_AIRFLOW", 96.2]], "S07 dropo | **FAIL** | docs/evidence/full-qa/gate10b/masking.json |
| QA-UI-001 | FR-010 | UI element inventory extracted from the live window | non-empty inventory; menus/shortcuts reported as found | QPushButton=10; QComboBox=10; QCheckBox=1; QLineEdit=11; QSpinBox=5; QDoubleSpinBox=2; QSlider=0; QListWidget=3; QTableWidget=2; QTextEdit=3; QTabWidget=0; menus=0; shortcuts=0; dialogs_in_code=2 | **PASS** | docs/evidence/full-qa/gate2/ui-inventory.json |
| QA-UI-002 | FR-010 | Mouse navigation across all six pages | pages.currentIndex follows the clicked row | 0:لوحة التحكم=ok; 1:مركز المصادر=ok; 2:قراءات الحساسات=ok; 3:سجل الأحداث=ok; 4:تفاصيل الحدث والتقرير=ok; 5:الإعدادات=ok | **PASS** | docs/evidence/full-qa/gate2/screenshots/02-page5-ar-light.png |
| QA-UI-003 | UI-001 | Source center shows only fields relevant to the selected source | no simulation settings for real-device sources; each source shows its own fields | mismatches: none | **PASS** | docs/evidence/full-qa/gate2/screenshots/03-source-network.png |
| QA-UI-004 | SIM-001..003 | Simulation sub-options follow mode and family | visibility matches the mode (faults, schedule, random settings) | mismatches: none | **PASS** |  |
| QA-UI-005 | NFR-001 | Start via button click: source locks, start disabled, values update while navigating | source combo locked, start disabled, sensor values change | running=True start_disabled=True source_locked=True sensors_changed=5 | **PASS** | docs/evidence/full-qa/gate2/screenshots/04-sensors-running.png |
| QA-UI-006 | NFR-001 | Stop via button: controls unlock and last data is labeled as stopped | source combo enabled; status says data is last received (not live) | stopped=True status='متوقف — القراءات المعروضة آخر بيانات مستلمة' running_status='قيد التشغيل — SIMULATION' | **PASS** |  |
| QA-UI-007 | NFR-001 | GUI stays responsive during a 30x session with AI | no gap > 1 s | ticks=686 max_gap=0.332s | **PASS** |  |
| QA-UI-008 | AI-005 | AI status card shows state and model version while running | contains 'AI:' and the model version | label='AI: نشط — نمط معتاد \| 0.431 \| iforest-cr005-v2' | **PASS** |  |
| QA-UI-009 | NFR-001 | Second session can start and stop after the first | controls return to idle | idle=True | **PASS** |  |
| QA-UI-010 | UI-001 | Double-click an event row opens the report page with a simple report | report page index 4 and non-empty simple report with AI section | events=1 opened=True len=1608 | **PASS** | docs/evidence/full-qa/gate2/screenshots/06-report-simple.png |
| QA-UI-011 | UI-002 | Technical details button reveals technical report and plot | report_text and time_plot visible | report_visible=True plot_visible=True | **PASS** | docs/evidence/full-qa/gate2/screenshots/07-report-technical.png |
| QA-UI-012 | SETTINGS-001 | English mode contains no leftover Arabic UI text | no Arabic characters in controls (event cells and preserved diagnostic text excluded) | 0 Arabic strings in EN mode:  | **PASS** | docs/evidence/full-qa/gate2/english-mode-arabic-text.json |
| QA-UI-013 | SETTINGS-001 | Layout direction RTL in Arabic and LTR in English | RTL then LTR | ar_rtl=True en_ltr=True | **PASS** |  |
| QA-UI-014 | CONN-001 | Invalid/unreachable network hosts are rejected without crash | an error is shown, window alive | '999.999.1.1'->تعذر إكمال العملية: '999.999.1.1' does not appear to be an IPv4 or IPv6 address \| 'example.com'->تعذر إكمال العملية: 'example.com' does not appear to be an IPv4 or IPv6 address \| ''-> | **PASS** |  |
| QA-UI-015 | CONN-001 | Missing replay file is reported | error label visible | error='تعذر إكمال العملية: [Errno 2] No such file or directory: 'C:\\Users\\user\\AppData\\Local' | **PASS** |  |
| QA-UI-016 | UI-001 | Start with replay and no file shows an error | error visible and window alive | error='تعذر إكمال العملية: [Errno 13] Permission denied: '.'' | **PASS** |  |
| QA-UI-017 | NFR-001 | Window close shuts the backend worker down | worker finished | worker_finished=True | **PASS** |  |
| QA-UI-018 | SETTINGS-001 | Reopening restores language/theme and previous events | language=en theme=dark and the earlier events listed | language=en theme=dark events=1 | **PASS** | docs/evidence/full-qa/gate2/screenshots/09-reopened-en-dark.png |
| QA-UI-019 | DATA-001 | Previous session data is not shown as live after restart | no live reading claim (no data yet) | age='No reading' context='No session started. Choose simulation in Data sources.' | **PASS** |  |
| QA-UI-020 | NFR-001 | Starting a second session while one is running is refused with a message | message shown; first session unaffected | {"second_start_message": "توجد جلسة قائمة؛ أوقفها قبل بدء مصدر آخر", "start_button_disabled_while_running": true, "source_locked": true} | **PASS** | docs/evidence/full-qa/gate8/negative-gui.json |
| QA-UI-021 | FR-006/NFR-001 | Export to an unwritable path shows a local error and does NOT stop the source or create a CONNECTION event (ol | error text, samples keep flowing, 0 CONNECTION events | {"export_to_missing_dir": "تعذر إكمال العملية: [Errno 2] No such file or directory: 'C:\\\\Users\\\\user\\\\AppData\\\\Local\\\\Temp\\\\cl", "export_to_directory": "تعذر إكمال العملية: [Errno 13] Per | **PASS** | docs/evidence/full-qa/gate8/negative-gui.json |
| QA-UI-022 | SETTINGS-001 | Changing language/theme during a session does not interrupt data | measurement count keeps increasing | samples continued | **PASS** |  |
| QA-UI-023 | UI-001 | Opening a report that does not exist shows a message and the window survives | text 'not found' and window alive | الحدث غير موجود | **PASS** |  |
| QA-UI-030 | UI-001 | Dashboard button 'اختيار مصدر البيانات' navigates to the source center | page index 1 | page=1 | **PASS** |  |
| QA-UI-031 | UI-001 | Every combo box: all items can be selected | each item selectable | {"language_combo": {"items": 2, "all_selectable": true}, "theme_combo": {"items": 2, "all_selectable": true}, "source_combo": {"items": 6, "all_selectable": true}, "family_combo": {"items": 2, "all_se | **PASS** |  |
| QA-UI-032 | UI-001 | Spin boxes clamp out-of-range values and respond to the keyboard | value clamped to the range; Up increases | {"network_port": {"min": 1, "max": 65535, "below->": 1, "above->": 65535, "up_key": 2, "clamped": true}, "fault_start": {"min": 0, "max": 150, "below->": 0, "above->": 150, "up_key": 1, "clamped": tru | **PASS** |  |
| QA-UI-033 | UI-001 | Typing into host/path fields and toggling the AI check box with the mouse | text appears; checkbox toggles | typed=('127.0.0.1', 'abc.jsonl') toggles=True,False (indicator hit at x=1229; the middle of the widget does not toggle) | **PASS** |  |
| QA-UI-034 | UI-001 | 'تحديث السجل' refreshes the event list without losing rows | same rows | rows 1->1 | **PASS** |  |
| QA-UI-035 | UI-001 | 'عرض تقرير الحدث المحدد' opens the selected event's report | report page with text | page=4 chars=1597 | **PASS** |  |
| QA-UI-036 | REPLAY | Export button: real file dialog -> session written as a Replay file that verifies | file created and ReplaySource.verify ok | exists=True bytes=1616466 verify={'ok': True, 'stages': ['FILE_VALID', 'SAMPLE_VALID'], 'samples': 776} | **PASS** |  |
| QA-UI-037 | REPLAY | Browse button: real file dialog fills the path field | path_input equals the chosen file | path='C:/Users/user/AppData/Local/Temp/claude/C--doccar/d8a9af6d-01f7-4fb1-be56-5ec89ed33b45/scratchpad/doctorcar-qa/controls/exported.jsonl' | **PASS** |  |
| QA-UI-038 | REPLAY | Verify button on a replay file reports success | details label changes and no error | details='فحص ناجح الملف صالح → العينات صالحة ' error_visible=False | **PASS** | docs/evidence/full-qa/gate2_controls/screenshots/controls-verify-replay.png |
| QA-UI-039 | REPLAY | Replaying the exported session through the UI yields events with origin REPLAY | >=1 event with origin REPLAY | replay events=[] | **FAIL** |  |
| QA-UI-040 | CONN-001 | 'تحديث المنافذ' fills the port list from the system; no port is opened | combo items == system COM ports | combo=4 system=['COM3', 'COM4', 'COM7', 'COM8'] | **PASS** |  |
| QA-UI-041 | IOT-001..003 | Network source from the UI: verify shows handshake stages, session runs, historical events are imported | details mention RECEIVING_DATA; 2 HISTORICAL events; status shows the source | verify='فحص ناجح HELLO → CAPABILITIES → تصل البيانات  Firmware: software-tcp-1 \| JSONL: 1' historical=2 status='قيد التشغيل — DEVICE_TEST' | **FAIL** | docs/evidence/full-qa/gate2_controls/screenshots/controls-verify-network.png |
| QA-XAI-001 | XAI-001/002 | XAI: deterministic, varies with the window, equals an independent recomputation from the pipeline | identical for the same window; different for another; \|difference\| < 1e-12 | same_window_identical=True other_window_differs=True max_independent_diff=0.00e+00 window_end=5000 model_sha_match=True | **PASS** |  |
| QA-XAI-002 | XAI-004 | Previously 'always zero' SPEED group: is it a real non-effect or an aggregation/display bug? | v1 never reads SPEED features (design), explanation flags used_by_model=false; v2 reads them | v1 reads 12 features, SPEED features read=[]; explanation says used=False effect=0.0; v2 reads SPEED features=[4, 6] | **PASS** |  |
| QA-XAI-003 | XAI-001 | No explanation for insufficient data, another model's result or inconsistent features | ValueError each time | all refused | **PASS** |  |
| QA-XAI-004 | XAI-003 | Report: no anomaly-factor text for a normal AI decision; for an anomalous one only computed positive groups, f | no 'العوامل' line for normal; shown groups subset of positive computed effects; xai.end_ms <= detection | normal_text_has_factors=False; anomalous shown=['air_fuel_operation', 'temperature', 'voltage'] positive=['air_fuel_operation', 'temperature', 'voltage'] xai_end=63000 detection=63000 | **PASS** |  |

## 7. العيوب

عدد العيوب المسجلة: **14** — التفاصيل في `DEFECT_REGISTER.md`.

CRITICAL: 0، HIGH: 2، MEDIUM: 7، LOW: 5

## 8. المخاطر

- نتائج الأداء كلها من مولد اصطناعي واحد: لا تثبت أداءً على مركبات.
- الاختبار البصري آلي عبر QTest ولقطات؛ لا فحص بشري لكل دقة/DPI.
- Firmware لم يُبنَ ولم يُشغَّل؛ كل ما سبق عنه مراجعة ساكنة.
- قاعدة المستخدم لم تُفحص ولا تُمس.

## 9. التغطية

- تغطية وظيفية: 51 Verified / 7 Partial / 2 Failed / 2 Not Tested / 3 Not Implemented من 65 بندًا.
- لم تُقَس تغطية الأسطر (أداة coverage غير مثبتة ولم أعدّل البيئة)؛ التغطية المذكورة وظيفية لا سطرية.

## 10. معايير الخروج

| المعيار | الحالة |
| --- | --- |
| الواجهة الأساسية تعمل | PASS |
| قراءات المحاكاة صحيحة وفق النموذج المعلن | PASS |
| الأعطال المحقونة تؤثر كما هو متوقع | PASS |
| اكتشاف أحداث مبررة | PARTIAL (القواعد قوية؛ تغطية ناقصة في ظروف محددة) |
| التسجيل دون فقد غير مبرر | PASS |
| ML يعمل وحدود دقته معروفة | PARTIAL (يعمل؛ لا قيمة مضافة مثبتة وإنذارات كاذبة متبقية) |
| XAI يفسر النموذج فعليًا | PASS |
| التقرير لا يعطي تشخيصًا قطعيًا | PASS |
| البيانات محفوظة ومستعادة | PASS |
| التكامل الشبكي التجريبي | PASS |
| لا أخطاء حرجة غير معالجة في مسار العرض | PASS (لا CRITICAL مسجل) |
| كل وظيفة غير مختبرة معلنة | PASS (مدرجة في الجرد) |
