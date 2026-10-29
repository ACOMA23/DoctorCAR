# دليل DoctorCAR السريع للكود (10 دقائق)

كل المسارات نسبة إلى `desktop/src/doctorcar/` ما لم يُذكر غير ذلك. التحقق من الكود تم فعليًا (أسماء الملفات والأصناف والدوال أدناه موجودة).

## الدقيقة 1 — ما الذي يفعله DoctorCAR؟
برنامج سطح مكتب (Python + PySide6) يقرأ قياسات تشبه OBD-II (RPM، السرعة، حرارة المحرك…) من **مصدر بيانات** (محاكاة، ملف Replay، جهاز عبر USB أو TCP محلي)، يتحقق من سلامتها، يكتشف أنماطًا غير طبيعية بالقواعد (والـML كمستشار)، ويحفظ في SQLite **30 ثانية قبل و30 ثانية بعد** كل اكتشاف، ثم يعرض تقريرًا عربيًا/إنجليزيًا. البيانات كلها محاكاة؛ لا مركبة حقيقية ولا Firmware مُختبَر.

## الدقيقة 2 — بنية المشروع
| المجلد | المحتوى |
| --- | --- |
| `core/` | `session.py` (المنسق الوحيد)، `models.py` (Sample/Event/Reading)، `sensor_registry.py` |
| `sources/` | `simulation.py`، `scenarios.py` (أعطال S01–S07)، `replay.py`، `serial_device.py`، `network_device.py`، `device_simulator.py` |
| `monitoring/` | `data_quality.py`، `event_detector.py`، `evidence_rules.py` (قواعد MS_*)، `event_recorder.py`، `ring_buffer.py` |
| `analysis/` | `windows.py`، `model.py`، `analyzer.py`، `explanation.py` (XAI)، `models/` (النماذج المحزومة) |
| `diagnostics/` | `human_report.py` (تقرير مبسط/فني)، `evidence.py`، `hypotheses.py` |
| `protocol/` | `codec.py` (JSONL v1)، `network_simulator.py` (جهاز TCP وهمي) |
| `storage/` | `sqlite_repository.py` |
| `ui/` | `main_window.py`، `worker.py`، `startup.py`، `splash.py`، `theme.py`، `widgets.py`، `localization*.py` |
خارج الحزمة: `desktop/tests/` (pytest)، `firmware/` (ESP-IDF، غير مبني)، `docs/` (ملف التحكم والأدلة)، `audits/` (فحوص QA مستقلة).

## الدقيقة 3 — بدء التشغيل
نقطة الدخول: `__main__.py` (`python -m doctorcar`). تنشئ `QApplication` ثم `Launcher` من `ui/startup.py`:
1. يقرأ `QSettings` (لغة/ثيم) ويعرض `SplashWindow` (`ui/splash.py`) بمراحل فعلية.
2. يبني `MainWindow(database)` (يبدأ `BackendWorker` الذي يفتح SQLite).
3. بالتوازي يشغّل `AIWarmup` (QThread) لتحميل النموذج والتحقق من بصمته.
4. عندما تجهز القاعدة والنموذج (أو يفشل النموذج دون إيقاف التطبيق) يعرض `MainWindow` ويغلق الـSplash؛ مهلة 30 ث وفشل القاعدة يعرض حوارًا. مثال: `--no-splash` يتجاوز الشاشة.

## الدقيقة 4 — مسار البيانات
```text
SimulationSource.read_measurements()  →  Sample (11 قراءة + DTC)
   → DataQualityValidator.validate_measurement()      (monitoring/data_quality.py)
   → SQLiteRepository.save_measurement()
   → EventDetector (قواعد) + AnomalyAnalyzer.push() (ML اختياري)
   → EventRecorder  → save_event()
```
الاستدعاء كله داخل `Session.step()` (`core/session.py`): خطوة واحدة = عينة واحدة. عينة مرفوضة تُحصى في `rejected` ولا تُخزَّن كقراءة صالحة.

## الدقيقة 5 — Session و BackendWorker
- `Session(source, repository, analyzer=None, ml_alerts=True)`: `start()`، `step()`، `stop()`. لا يعرف شيئًا عن الواجهة.
- `ui/worker.py::BackendWorker(QThread)`: خيط واحد يملك المصدر والـSession واتصال SQLite. يستقبل أوامر من الواجهة عبر `submit("start"|"stop"|"report"|…)` (طابور حجمه 32) وينفذها في `run()`، ويرسل النتائج **إشارات** Qt: `snapshot`، `events_changed`، `ai_changed`، `status_changed`، `error`، `session_stats`… `MainWindow` يربطها بدوال العرض (`show_sample`, `show_events`, `set_status`). القاعدة الذهبية: لا يُلمس أي Widget من الخيط الخلفي؛ كل شيء يعبر بالإشارات.

## الدقيقة 6 — المحاكاة وحقن الأعطال
`sources/simulation.py::SimulationSource` يولّد رحلة طبيعية (تشغيل بارد ثم قيادة؛ 155 ث وتتكرر دورتها إن طالت) بخطوة 200 ms. الأعطال من `sources/scenarios.py`: `ScenarioInstance("S01", start_ms, duration_ms, severity)` ثم `apply_scenarios()` تعدّل قراءات مترابطة (مثلًا S01 حرارة تتصاعد، S02 تسرب هواء). الحقيقة المرجعية (ما حُقن) تحفظ في `simulation_runs` للتقييم فقط، ولا تصل للكواشف.
مثال: `SimulationSource(seed=4100, scenario_family="multisensor", mode="FAULT_INJECTION", scenarios=(ScenarioInstance("S01", 60000, 35000),))`.

## الدقيقة 7 — محرك الكشف ودورة حياة الحدث
القواعد في `monitoring/evidence_rules.py` (`RULES`)؛ كل قاعدة تنظر إلى **علاقات** بين الحساسات على نافذة زمنية وتُخرج: أدلة داعمة ومعارضة وبيانات ناقصة وفحوصًا مقترحة (`diagnostics/hypotheses.py`). عند الإطلاق: `EventRecorder` يبدأ حدثًا `RECORDING` ويجمع العينات اللاحقة، ثم `COMPLETE` عند T+30 ث أو `PARTIAL` إن انتهت الرحلة قبلها. حدث من نوع مماثل داخل نافذة مفتوحة يُدمج؛ ما يبدأ عند T+30 بالضبط يأخذ حدثه.

## الدقيقة 8 — ML و XAI
- `analysis/windows.py::WindowBuilder` يبني نافذة سببية 5 ث (خطوة 1 ث) من عينات صالحة فقط (47 ميزة).
- `analysis/model.py::AnomalyModel` يحمّل نموذج IsolationForest من `analysis/models/<name>/` **بعد مطابقة SHA-256** (`TRUSTED_SHA256`)؛ الافتراضي `cr006-iforest-v3`؛ `infer(window)` يعيد `decision` (NORMAL/ANOMALOUS/INSUFFICIENT_DATA) ودرجة.
- `analysis/analyzer.py::AnomalyAnalyzer.push(sample)` يشغّل النافذة ويطبق بوابة استمرار (4 نوافذ متتالية).
- **لماذا استشاري؟** استدعاؤه وحده ضعيف (7.5% على اختبار مستقل) فالتطبيق ينشئ `Session(..., ml_alerts=False)` في `ui/worker.py`: ML لا يفتح حدثًا، فقط يُربط تحليله بحدث فتحته قاعدة (آخر تحليل `end_ms ≤ T` وعمره ≤ 2 ث).
- XAI: `analysis/explanation.py::explain(model, result)` يستبدل مجموعات ميزات بخلفية مرجعية ويقيس تغيّر **درجة النموذج**؛ للقرارات ANOMALOUS فقط، ولا يدّعي سببًا ميكانيكيًا.

## الدقيقة 9 — تسجيل الأحداث وSQLite
`monitoring/ring_buffer.py::TimeRingBuffer(30_000)` يحتفظ بآخر 30 ث؛ `EventRecorder(pre_ms=30_000, post_ms=30_000)` يدمج ما قبل الحدث وما بعده. `storage/sqlite_repository.py::SQLiteRepository`: `save_measurement`، `save_event`، `list_events`، `get_event`، `export_session` (يصدّر Replay). الجداول: sessions، measurements، events، event_samples، analyses، event_analyses، event_ai_status، detection_evidence، diagnostic_reports، simulation_runs. التقرير: `diagnostics/human_report.py::build_report_model` ثم `render_simple`/`render_technical(report, "ar"|"en")` من حدث مخزن، لا من حالة حية.

## الدقيقة 10 — الواجهة وIoT ونقاط التعديل
- الواجهة: `ui/main_window.py` ست صفحات (`navigation` + `pages`)، الألوان والـQSS في `ui/theme.py` فقط، المكونات في `ui/widgets.py`، الترجمة في `ui/localization*.py` (`MainWindow.t()`).
- IoT: `protocol/network_simulator.py` يخدم جهازًا على 127.0.0.1 (HELLO → CAPABILITIES → SAMPLE/EVENT، JSONL v1)؛ `sources/network_device.py::NetworkDeviceSource` يتصل (يرفض غير loopback) ويحوّل الرسائل إلى `Sample` عبر `protocol/codec.py`. الأحداث التاريخية المرفوعة تُحفظ مباشرة ولا تمر بالكاشف أو ML.

### مخطط المعمارية
```text
DataSource (sim/replay/serial/TCP)
   → DataQualityValidator → Session.step() ─┬→ EventDetector (rules) ─┐
                                            └→ AnomalyAnalyzer (ML)  ─┤ (استشاري)
   → EventRecorder + TimeRingBuffer (T±30 s) ◄───────────────────────┘
   → SQLiteRepository → BackendWorker ──signals──→ MainWindow / Reports
```

## أهم 10 ملفات (بالترتيب)
1. `core/session.py` 2. `ui/worker.py` 3. `core/models.py` 4. `monitoring/evidence_rules.py` 5. `monitoring/event_recorder.py` 6. `storage/sqlite_repository.py` 7. `sources/simulation.py` + `sources/scenarios.py` 8. `analysis/model.py` + `analyzer.py` 9. `diagnostics/human_report.py` 10. `ui/main_window.py` (ثم `ui/startup.py`).

## 5 تعديلات شائعة
| التعديل | أين |
| --- | --- |
| إضافة حساس | `core/sensor_registry.py` + حدود في `monitoring/data_quality.py` (`PHYSICAL_BOUNDS`) + المحاكاة |
| قاعدة كشف جديدة | `monitoring/evidence_rules.py` (`RULES`) ثم نص التقرير في `diagnostics/` |
| سيناريو عطل جديد | `sources/scenarios.py` (`SCENARIOS_MS`) |
| تغيير لون/خط/مسافة | `ui/theme.py` فقط |
| نص جديد بالإنجليزية | `ui/localization_ux.py` (`UX_AR_EN`) أو `localization.py` |
> أي نموذج ML جديد: مجلد باسم جديد في `analysis/models/` وبصمته في `TRUSTED_SHA256`، ولا تُعد تدريب الموجود دون تكليف.

## 5 أسئلة عرض محتملة
1. **هل الـAI يشخّص العطل؟** لا؛ استشاري، يخص نمط القياسات، والأحداث الأساسية من القواعد.
2. **ماذا يعني XAI هنا؟** أثر مجموعات الميزات على درجة النموذج نفسه، وليس سببًا ميكانيكيًا.
3. **هل جُرّب على سيارة؟** لا؛ محاكاة فقط، والـFirmware غير مبني وغير مختبر على لوحة.
4. **لماذا 30 ث قبل وبعد؟** لأن الأعطال العابرة لا تترك DTC؛ نافذة T±30 تحفظ سياقها (`PARTIAL` إن لم تكتمل).
5. **كيف نضمن عدم تسرب الحقيقة المرجعية للكواشف؟** الحقن محفوظ في `simulation_runs` لا يقرؤه إلا التقييم، والنوافذ سببية ولا تحمل أسماء السيناريوهات (مُختبر).
