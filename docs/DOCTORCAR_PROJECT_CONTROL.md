# DOCTORCAR — Project Control

## DC-CR-005 — Engineering Recovery & AI Calibration (تنفيذ، 2026-10-28)

**إشعار حالة:** هذا القسم يتقدم على كل ما يليه. عبارات «لا ML/XAI» و«M2/M3 Planned» في الأقسام التاريخية أدناه كانت صحيحة وقت كتابتها، وأُلغيت بتنفيذ DC-CR-004 ثم DC-CR-005. تقاس الحالات هنا بالمفردات: **IMPLEMENTED** (موجود) · **VERIFIED** (موجود واجتاز اختبار قبول معاد تشغيله، ضمن المحاكاة فقط) · **PARTIAL** · **FAILED** · **NOT TESTED**. وجود الكود لا يعني VERIFIED.

**البداية (Gate 0):** `156 passed / 0 failed / 0 skipped` في 48.03s، exit 0؛ `evidence/dc-cr-005/baseline.log/xml`. البيئة في `environment.txt` (Python 3.14.6، numpy 2.5.4، scikit-learn 1.9.1، joblib 1.6.0). بصمات الملفات المحمية (النموذج v1، dataset v1، Firmware، `audits/test_m1_acceptance.py`) في `protected-before.sha` وتطابقت بعد العمل في `protected-after.sha`.

**الخاتمة:** الانحدار الكامل `193 passed / 0 failed / 0 errors / 0 skipped` في 441s (156 سابقة: تأكيداتها لم تتغير، وفي ثلاثة منها من CR-004 صار اختيار v1 صريحًا بقرار D20 + 37 جديدة). Ruff وformat وmypy strict وpip check في `quality.log`. **CR-005: PASS وظيفي ضمن المحاكاة؛ AI-009 PARTIAL؛ M1 يبقى PARTIAL (A07 وبناء Firmware وعتاد).**

### تحليل الأثر والسبب الجذري

| المشكلة | السبب الجذري المثبت | الإصلاح | الملفات | الخطر | الاختبار |
| --- | --- | --- | --- | --- | --- |
| إنذار ML كاذب عند البدء البارد (~7s) والتوقف | v1: 12 رحلة تدريب فقط، عتبة F1 على نوافذ مفردة بلا قيد إنذارات، 12 ميزة اختيرت بالنظر لأداء استكشافي | dataset-3 (60 رحلة تدريب طبيعية بمعاملات قيادة وبدء بارد/دافئ متنوعة)، تدريب v2، اختيار الميزات والعتبة وعدد النوافذ المتتالية على Validation فقط بقيد 0 إنذار كاذب على مستوى الحدث | `analysis/benchmark.py`، `analysis/models/cr005-iforest-v2/` | انخفاض استدعاء ML وحده | `test_benchmark.py` |
| تقييم يقيس نوافذ لا أحداثًا | `experiment.evaluate` يحسب نافذة/ثانية بلا سياسة التطبيق | `PersistenceGate/DetectionPolicy` واحدة للتطبيق والتقييم؛ مطابقة حدث-بحدث بقواعد معلنة | `analysis/analyzer.py`، `benchmark.py` | — | `test_benchmark.py` |
| حدث القواعد عند 68.2s بلا تحليل AI | الربط يشترط `trigger.timestamp_ms == analysis.end_ms` ونوافذ ML تنتهي عند ثوانٍ صحيحة | ربط سببي: آخر نافذة `end_ms ≤ T` في الجلسة نفسها وعمرها ≤ ضعف الإزاحة (2000ms)؛ سبب موثق عند الغياب؛ التحليل اللاحق يُربط منفصلًا | `core/session.py`، `storage/sqlite_repository.py` (جدول `event_ai_status`)، `analysis/status.py` | توسعة DB | `test_ai_linking.py` |
| XAI مضلل | صفر دائم لمجموعة غير مقروءة؛ عنوان «زاد الشذوذ» لقرار طبيعي | `used_by_model` واتجاه التأثير وتأثير الميزات الفردية؛ XAI لقرارات ANOMALOUS فقط | `analysis/explanation.py`، `human_report.py` | تغيير شكل خرج XAI (إضافات فقط) | `test_report_ai.py` |
| Wheel بلا نموذج؛ lock بلا ML | النموذج خارج الحزمة (`parents[3]`) | النماذج داخل `analysis/models/` وpackage-data، تثبيت pinned hash، extras `[ml]`/`[train]`، lock محدّث | `pyproject.toml`، `requirements-lock.txt`، `analysis/model.py` | — | `test_packaging.py` + تثبيت جديد |

### متطلبات CR-005

| ID | الوصف | الحالة | الدليل |
| --- | --- | --- | --- |
| DOC-005 | مصالحة README وملف التحكم مع الكود | VERIFIED | هذا القسم، README §10 |
| AI-007 | dataset-3 مفصول وتدريب v2 دون تسرب | VERIFIED (محاكاة) | `dataset/manifest.json`, `model-v2-metadata.json`, test_benchmark |
| AI-008 | تقييم نافذة وحدث بسياسة التطبيق، v1 مقابل v2 على Test مستقل | VERIFIED (محاكاة) | `evaluation_events_test.json` |
| AI-009 | خفض الإنذارات الكاذبة | PARTIAL | الإنذارات الكاذبة انخفضت لكن بقيت 3 (ML وحده)، واستدعاء ML وحده 0.10 |
| INT-003 | ربط تحليل AI بالأحداث سببيًا مع الحالات | VERIFIED | test_ai_linking (68.0/68.2) |
| XAI-004 | صحة XAI وعدم التضليل | VERIFIED للدالة؛ PARTIAL للتغطية | test_report_ai؛ مجموعات خشنة |
| UX-004 | تقرير مستخدم/فني وحالة AI في الواجهة | VERIFIED | test_report_ai, test_integration |
| PKG-001 | Wheel بنموذج وتثبيت جديد | VERIFIED | `installed-package.json` |
| TEST-003 | انحدار كامل وتكامل | VERIFIED | `final.log/xml`, `quality.log` |
| FW-001 | بناء Firmware وA07 | NOT TESTED / A07 OPEN | `firmware-status.json` |

### نتائج النموذجين على Test المستقل (66 رحلة، 2.84 ساعة محاكاة، 30 رحلة طبيعية، 40 حدثًا حقيقيًا)

**مستوى الحدث (سياسة التطبيق):**

| الكاشف | أحداث مكتشفة | Recall | إنذارات | إنذارات كاذبة (على رحلات طبيعية) | Precision | كاذبة/ساعة | تأخر وسيط (ث) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Rules فقط | 40/40 | 1.000 | 52 | 0 (0) | 1.000 | 0.00 | 6.0 |
| ML v1 | 18/40 | 0.450 | 149 | 131 (59) | 0.121 | 46.10 | 3.0 |
| ML v2 | 4/40 | 0.100 | 7 | 3 (1) | 0.571 | 1.06 | 14.0 |
| Rules + ML v1 | 40/40 | 1.000 | 183 | 131 (59) | 0.284 | 46.10 | 3.0 |
| Rules + ML v2 | 40/40 | 1.000 | 55 | 2 (1) | 0.964 | 0.70 | 6.0 |

**مستوى النافذة (ثانية/نافذة؛ ليس أداء الكاشف المنشور):**

| النموذج | TP | FP | FN | TN | Precision | Recall | F1 | FP window/ساعة |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cr004-iforest-v1 | 336 | 1332 | 628 | 7610 | 0.201 | 0.349 | 0.255 | 484.1 |
| cr005-iforest-v2 | 101 | 543 | 863 | 8399 | 0.157 | 0.105 | 0.126 | 197.3 |

**الاستدعاء حسب السيناريو (مكتشف/أحداث):**

| السيناريو | Rules | ML v1 | ML v2 | Rules+ML v1 | Rules+ML v2 |
| --- | --- | --- | --- | --- | --- |
| S01 | 5/5 | 1/5 | 0/5 | 5/5 | 5/5 |
| S02 | 5/5 | 5/5 | 0/5 | 5/5 | 5/5 |
| S03 | 5/5 | 5/5 | 2/5 | 5/5 | 5/5 |
| S04 | 5/5 | 2/5 | 0/5 | 5/5 | 5/5 |
| S05 | 5/5 | 5/5 | 1/5 | 5/5 | 5/5 |
| S06 | 7/7 | 0/7 | 1/7 | 7/7 | 7/7 |
| S07 | 8/8 | 0/8 | 0/8 | 8/8 | 8/8 |

**قواعد المطابقة:** نافذة الحدث الحقيقي `[start, start+duration+10s]`؛ إنذار ضمن النافذة = كشف، خارجها = إنذار كاذب؛ إنذارات المصدر نفسه خلال 30s حدث واحد (سلوك المسجل)؛ كشف قاعدة وML خلال 10s حدث واحد (سلوك Session)، ويطابق الحدث المدموج إذا وقع أي عضو في النافذة. سياسة v1: 3 نوافذ متتالية؛ v2: 5. **تصحيح تقييم موثق:** أول تشغيل نسب الحدث المدموج لأبكر أعضائه فسجل 39/40 للمدموج؛ صُحح منطق المطابقة فقط بعد رؤية النتائج (دون تغيير نموذج أو عتبة)، وهو الرقم المعتمد. لم يُضبط شيء على Test.

### قرارات DC-CR-005

- D19: النموذج الافتراضي **v2** (`iforest-cr005-v2`). المبرر: إنذارات ML الكاذبة 131 → 3 (46.1 → 1.06/ساعة)، ودقة الدمج 0.28 → 0.96، دون خسارة في الكشف المدمج (40/40). **الإفصاح:** استدعاء ML وحده انخفض 0.45 → 0.10، والقواعد وحدها بلغت 40/40 بلا إنذار على هذا الاختبار؛ فلا قيمة كشف مضافة لـML مثبتة فوق القواعد في هذه المحاكاة. v1 محفوظ وقابل للاختيار (`AnomalyModel("cr004-iforest-v1")`).
- D20: ثلاثة اختبارات CR-004 (`test_live`, `test_ml` split، `test_unified`) تفترض v1؛ جُعل اختيار v1 فيها صريحًا فقط وبقيت تأكيداتها كما هي. لم تُعدّل اختبارات M1/CR002/CR003 أو `audits/`.
- D21: XAI يُحسب لقرارات ANOMALOUS فقط؛ القرار الطبيعي يعرض أنه لا توجد عوامل لتفسيرها.
- D22: العمر الأقصى لتحليل مربوط بحدث = ضعف إزاحة النافذة (2000ms).
- D23: تبعيات الاستدلال (`numpy, scikit-learn, joblib`) في extra `[ml]`؛ `pandas` للتدريب فقط في `[train]`؛ بدون `[ml]` يعمل التطبيق بالقواعد ويعرض «النموذج لم يُحمّل» مع السبب.

### القيود المتبقية

- كل الأرقام من مولد اصطناعي واحد في كل المجموعات (بذور ومعاملات قيادة مختلفة)؛ لا تثبت أداء على مركبات.
- الإنذارات الكاذبة المتبقية لـv2 كلها عند 63–64s (انتقال التسارع إلى السير) في رحلات باردة بمعامل قيادة ≥ 1.10.
- ML لا يلتقط S01/S02/S04/S07 عمليًا (0/5، 0/5، 0/5، 0/8)؛ القواعد هي مصدر الكشف الفعلي.
- XAI مجموعات خشنة غير SHAP، وتأثيرات غير جمعية.
- Firmware: لا ESP-IDF على الجهاز، A07 مفتوح، `event_upload=false`، لا Wi-Fi/CAN/MicroSD، لا تشغيل على لوحة. الجهاز الشبكي المحاكي ليس مركبة.


## DC-CR-004 — طلب نشط، بوابات تحقق مستقلة

التفويض الجديد يجيز ML/XAI وTCP محليًا فوق المشروع القائم. خط الأساس قبل التعديل: **138 passed في29.60s، exit0**؛ لا فشل أو تخطٍ. الدليل `evidence/dc-cr-004/baseline.log/xml`. حُفظت بصمات الاختبارات السابقة وFirmware في `protected-before.json`.

الأولوية Must لكل صف. الحالات التالية تخص DC-CR-004؛ متطلبات M1 ذات المعرف نفسه تبقى مستقلة. لا يثبت نجاح البرمجيات جهازًا أو مركبة.

| ID | Description / Component | Dependencies | Acceptance Criteria | Implementation Files | Test Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| UX-001 | تقرير مبسط افتراضي / diagnostics, UI | Gate0 | أرقام فعلية و2–4 قراءات ولغة مفهومة | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| UX-002 | تفاصيل فنية محفوظة / UI | UX-001 | توسيع التفاصيل والقياسات دون فقد | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| UX-003 | نموذج تقرير موحد / diagnostics | UX-001 | فصل البيانات عن عرض AR/EN وتوافق التاريخ | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| AI-001 | تجهيز Dataset / analysis | Gate1 | رحلات مستقلة وmanifest | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| AI-002 | نوافذ زمنية وميزات / analysis | AI-001 | زمن/فجوات/جودة/schema دون مستقبل | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| AI-003 | تدريب وحفظ / analysis | AI-002 | IsolationForest حقيقي وعتبة validation | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| AI-004 | استدلال / analysis | AI-003 | استعادة artifact موثوق ودرجات متغيرة | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| AI-005 | دمج الكشف / Session | AI-004 | فشل ML لا يوقف القواعد؛ مسجل واحد | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| AI-006 | تقييم / analysis | AI-003 | Rules/ML/Combined على test نفسه | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| XAI-001 | تفسير النموذج / analysis | Gate3 | تأثيرات محسوبة على درجة النموذج | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| XAI-002 | Fidelity / tests | XAI-001 | تحقق عددي للدرجة بعد perturbation | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| XAI-003 | تفسير مفهوم / reports | XAI-001 | لا سبب ميكانيكي أو احتمالات قطع | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| IOT-001 | محاكي TCP / protocol | Gate4 | عملية مستقلة localhost JSONL1 | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| IOT-002 | مصدر TCP / sources | IOT-001 | مصافحة وحدود ورسائل صالحة | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| IOT-003 | مزامنة تاريخ / storage | IOT-002 | استعادة idempotent دون AI مزيف | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| IOT-004 | تعافي الاتصال / sources | IOT-002 | إعادة اتصال محدودة وجلسات معزولة | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| INT-001 | تسجيل الحدث / recorder | Gate3 | T±30 دون عينات ضائعة | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| INT-002 | توافق التشخيص / diagnostics | Gate6 | القواعد وML وXAI والفرضيات منفصلة | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |
| TEST-001 | قبول شامل / tests,audits | Gate6 | Regression وE2E وbenchmark وأدلة خام | قيد التحديد بعد التنفيذ | لم ينفذ بعد | Planned |

البوابات بالترتيب: 0 baseline PASS →1 تقارير →2 Dataset/Training →3 Live →4 XAI →5 TCP →6 تقرير موحد →7 قبول. جميع البوابات1–7 لم تُقبل بعد. أثر التغيير: توسعة diagnostics؛ analysis اختيارية؛ Session نفسه وEventRecorder نفسه؛ تخزين تحليلات إضافي متوافق؛ TCP يعيد استخدام ProtocolReceiver. لا تعديل اختبارات سابقة أو CAN أو تفليش.

## A. Project Identity

DoctorCAR 0.1.0؛ تحديث 2026-10-28 بتوقيت الرياض. مشروع جديد في `C:\doccar`.
التكليف الحالي DC-CR-003 داخل M1 فقط: **PASS للنطاق البرمجي الوظيفي المختبر؛ M1 PARTIAL**.138 اختبارات ناجحة،107 سابقة و31 جديدة، دون فشل/أخطاء/تخطي. كُشف16/21 نمطًا مجدولًا مع خمس حالات غير مكتشفة معلنة؛ لا دقة تشخيص سببي مقاسة. A01..A06 مصححة من CR002 وA07 مفتوحة في Firmware غير المعدل وغير المبني. لا ML/XAI ولا M2/M3 ولا عتاد.
هذا الملف هو مرجع الحالة الوحيد؛ الأدلة الخام في `docs/evidence/` ليست تقارير حالة بديلة.

### DC-CR-003 — Baseline / Impact Analysis

الطلب الحالي تطوير سيناريوهات S01..S07 وقواعد أدلة متعددة القياسات داخل المحاكاة وEventDetector وEvidence/Hypotheses/Report القائمة، مع حفظ T±30 والواجهة والإعدادات والتاريخ وReplay. لا Firmware ولا CAN ولا ML/XAI ولا قاعدة ثانية. البداية الفعلية: **107 passed / 0 failed / 0 skipped في18.98s، exit0**؛ `evidence/dc-cr-003/baseline.log/xml`. حفظت بصمات22 ملفًا: جميع اختبارات M1/CR002/القبول القديم وFirmware؛ لا تعديل لها.

تدقيق البداية: FaultInstance يغير إشارة واحدة غالبًا، وmisfire_pattern/air_pattern يغيران عدة إشارات بنسب مبسطة. المجدول الحالي يدعم دورات30s لكن المدد أقل من دورة. EventDetector يطبق حرارة108°C/3s وDataQuality فقط، دون تحليل نافذة علاقات. Evidence يحفظ أعلى حرارة/count/DTC/FreezeFrame والتوقيت؛ Hypothesis يفصل السبب المحتمل عن الدليل لكن بلا مقارنة متعددة المتغيرات. المسجل مستقل عن دورات الحقن ويحفظ الحدث بعد زوال الخلل؛ لا يحتاج استبدالًا.

الأثر المخطط: sources/scenarios.py جديد لتعريف وتطبيق وجدولة نماذج مترابطة؛ SimulationSource يظل مصدر الرحلة الطبيعي الوحيد. monitoring/evidence_rules.py جديد لحساب العلاقات التجريبية كدوال يستعملها EventDetector نفسه وEvidenceBuilder، لا محرك ثانٍ. تحسين diagnostics/evidence.py/hypotheses.py/reports.py والتقييم اللاحق وworker/MainWindow/localization فقط. تبقى عقود Sample/Event وQuality وJSONL v1 وSQLite v2 والمسجل دون تغيير. تعرض عائلة المحاكاة القديمة للتوافق، وعائلة متعددة القياسات ذات معرف معايرة عام لكل عيناتها الطبيعية وغير الطبيعية؛ هذا المعرف ليس اسم عطل ولا Ground Truth، ولا تستخدم القواعد Fault/Scenario ID. الحدود تخص النموذج المعلن فقط.

| المتطلب | الحالة عند البدء | دليل القبول المخطط |
| --- | --- | --- |
| MS-SIM | Completed | test_ms_simulation: التعريفات والسياق والعودة والتداخل والSeed؛ test_ms_diagnostics: نافذة عابرة للدورة |
| MS-RULE | Completed | test_ms_diagnostics: الأنماط السبعة، مدخلات عمياء، بدائل، وحدات/فجوات/غياب مراجع وتصنيف مشتق |
| MS-REPORT | Completed | A..K وقيم فعلية واستبعاد المستقبل واستعادة متطابقة؛ example-event.json/example-report-ar.txt |
| MS-UI | Completed | test_ms_integration_ui + e2e.json: اختيار العائلة والمقارنة والسجل والتقرير وAR/EN/الثيم السابق |
| MS-REG | Completed | final.xml:138 ناجحة؛107 سابقة دون تعديل و31 جديدة؛ quality.log وprotected-after.json |

المراحل المتتابعة: (1) نماذج/جدولة ثم اختبار؛ (2) قواعد/أدلة/تقارير ثم إيجابي وسلبي وغياب مراجع؛ (3) UI/تقييم ثم تجربة كاملة؛ (4) regression وتوثيق. لا ثقة ميكانيكية رقمية غير معايرة، ولا Fuel Pressure PID أو DTC/FreezeFrame مخترع. تبقى A07 مفتوحة وM1 PARTIAL.

### DC-CR-003 — نتائج القبول والتتبع النهائي

**النطاق الوظيفي CR003: PASS؛ M1: PARTIAL**. أعيد الاختبار فعليًا: **138 passed / 0 failed / 0 errors / 0 skipped في72.08s، exit0**؛ منها107 سابقة و31 جديدة. `evidence/dc-cr-003/final.log/xml`. خط الأساس107 في18.98s. نجحت بوابات التنفيذ بالترتيب: محاكاة+أساس39، قواعد/تقارير28، أول regression135، ثم UI/تكامل3، وأخيرًا138. لم تُعدّل اختبارات سابقة أو Firmware. A01..A06 تبقى مصححة، A07 C مفتوح خارج CR، ولم تنفذ اختبارات بناء/لوحة/USB فعلي.

| معيار القبول | النتيجة | الدليل الفعلي تحت desktop/tests/cr003 إلا ما يذكر |
| --- | --- | --- |
| AT-MS-01 | PASS | test_ms01_normal_no_rules_false_alarm؛ ثلاث رحلات إضافية Seeds42/73/97 بلا إنذارات |
| AT-MS-02 | PASS | S01→MS_THERMAL بقياسات حرارة/ميل/حمل/سرعة/RPM/خانق فعلية |
| AT-MS-03 | PASS | S02→MS_AIR_FUEL، وS03/S04 بعلاقات وقود/مراجع مختلفة؛ ليس تطابق اسم |
| AT-MS-04 | PASS | تياران عميان بSTFT=22% لكن علاقات الهواء مختلفة؛ فرضيتان وفحوص ونواقص؛ phase/raw مضللان لا يغيران النتيجة |
| AT-MS-05 | PASS | MS_SUPPLY يتطلب جهدًا ومفقودات متزامنة؛ انخفاض الجهد وحده لا يكفي؛ صفر الجهد يبقى قيمة؛ CONNECTION لا يتحول إلى كهرباء مركبة |
| AT-MS-06 | PASS | S06 لمدة9s يختفي ويستمر الحدث حتىT+30؛ فترات طبيعية بين نبضاته |
| AT-MS-07 | PASS | دورات30s وجدول45s عابر للدورة، تداخل S01+S02 وتسجيل متداخل من Session نفسها دون restart |
| AT-MS-08 | PASS | Seed83 نفسه يطابق الجدول وكل القراءات؛25Seed لفحص المدد والتعارض؛ عرض السرعة لا يدخل المولد |
| AT-MS-09 | PASS | إحصاءات min/max/mean/delta من القراءات المخزنة، علاقة ضغط+12kPa/MAF−30% في مدخلات اختبار مستقلة؛ تغيير ما بعدT لا يغير دليل الكشف |
| AT-MS-10 | PASS | A..K وفرضيات متعددة وداعم/معارض متاح/ناقص/فحص/حدود، مع إقرار صريح بعدم كفاية دليل السبب |
| AT-MS-11 | PASS | MISSING/INVALID/STALE/UNSUPPORTED والوحدات والفجوات تمنع قاعدة تفتقد المراجع؛ MAP ثابتة مع مراجع ثابتة لا تكفي |
| AT-MS-12 | PASS | GUI→SQLite→تقرير AR ثمEN→إغلاق/فتح وتقرير مطابق؛ سلامةSQL وFK |
| AT-MS-13 | PASS |107 اختبارات M1/CR002/قبول قديم؛ Replay جديد يحتفظ بمعايرة النموذج والكشف، fakeUSB/تاريخ/إعدادات كما هي |
| AT-MS-14 | PASS |71 M1 الأصلية +6 القبول السابقة +30 CR002 نجحت دون تعديل؛ بصمات22 ملفًا محفوظة، A07 ثابت وليس اختبارًا ناجحًا |

**تقييم الأنماط، لا دقة السبب الميكانيكي:** `simulation-evaluation.json` يحفظ21 حالة مجدولة مع السيناريو/الشدة/المدة/Seed، الأنماط والفرضيات والأدلة والفحوص ونتائج المطابقة.7/7 أمثلة تطوير و9/14 تنويعات معلمات =16/21 تطابق نمط مدعوم؛ خمس حالات غير مكتشفة، صفر أحداث نمط غير متطابقة، وصفر إنذارات في3 رحلات طبيعية وفي الفترات الطبيعية المعروفة للمجموعة. هذه تنويعات لنموذج واحد، وليست تحققًا مستقلًا على مركبات أو معايرة ثقة. `causal_diagnostic_accuracy=NOT_MEASURED`؛ وجود حدث أو DATA_QUALITY وحده لا يحتسب تشخيصًا صحيحًا. مرشح بلا أدلة يبقى unverified، ولا يحسب نجاحًا.

الحالات غير المكتشفة محفوظة دون إخفاء: S01/S02/S04/S05 عند55s ولمدة9s وشدة0.65؛ وS07-flatline عند80s/20s/0.9 مع مراجع قيادة شبه ثابتة. التعريفات مشروطة بدوران المحرك؛ جدول الحقيقة يصف الطلب وشروط تفعيله، ولا يثبت وحده ظهور أثر ميكانيكي. نهاية المراقبة قبل اكتمال نافذة التقييم تصنف CENSORED. المطابقة اللاحقة تسمح بذاكرة8s بعد نهاية الحقن، ولا تستعمل لإسناد السبب.

تجربة native Qt الحالية `e2e.json`: S02 عند60s/35s، كشف66s، نافذة36..96s/301 عينة، COMPLETE، حفظ واسترجاع تقرير مطابق، SQL integrity=ok وforeign_key_check فارغ. المثال `example-event.json`: خلال58..66s، MAF residual=−13.8163%، MAP residual=+4.0730kPa، STFT mean=12.0549%، load mean=46.1195%. الفرضيات: هواء غير مقاس أو انحراف قياس/قصور وقود؛ الفحص: اختبار تسرب مناسب والأنابيب ومقارنة MAF/MAP/التصحيحات، وقياسات خارجية عند الحاجة. هذه أرقام مقاسة من التشغيل، لا قيم متوقعة أُدرجت من الجدول.

قرارات التنفيذ:
- توسيع المصدر الحالي وEventDetector/Builder/Evaluator/Report؛ دوال العلاقات في monitoring/evidence_rules.py ليست محركًا أو خدمة ثانية. Session/EventRecorder/SQLite والعقود وQuality وJSONL لم تُستبدل.
- معرف معايرة عام واحد للعائلة الجديدة، في الرحلات الطبيعية والمضطربة وReplay؛ لا يحمل Fault ID. لا تستورد وحدات الاستدلال sources/faults أو scenarios أو جدول الحقن. Source→Session→Detector لا يمرر أسماء السيناريوهات.
- مراجع النموذج العامة MAF=RPM×(0.002+0.00008×load)، MAP=30+0.65×load؛ الحدود اختيارات هندسية من أمثلة التطوير، لا مواصفات مصنع أو نسب ثقة. RuleDefinition يحتوي القياسات والصلاحية والظروف والنافذة والعلاقات والبدائل والفحوص والنواقص؛ المصدر التفصيلي للكميات evidence_rules.py ودليل README4.6.
- نافذة العلاقات8s، ≥3 عينات و≥1s دون فجوة>1.5s؛ استبعاد المراجع غير الصالحة ووحداتها الخاطئة. MS_SIGNAL يسمح بالهدف الناقص/INVALID مع مراجع صحيحة. التصنيف مشتق فقط، وقد يبقى UNRESOLVED؛ لا تعديل Quality أو قياسات DB.
- إحصاءات التقرير B لكل النافذة؛ علاقات C تنتهي عندT فقط. عدد الأدلة هو عدد المقاييس الكمية، وليس عدد براهين مستقلة أو ثقة. عند عدم توفر معارض مستقل يصرح التقرير بذلك ولا يختلقه.
- جدول الدورات منفصل، والكتابات المتعارضة مرفوضة؛ التركيب بترتيب حتمي للتأثيرات المتوافقة، لا ادعاء نموذج فيزيائي أو تبديل حر للترتيب. التسجيلT±30 لا يتغير عند التعافي أو الدورة.

الملفات الجديدة: core/simulation_profile.py (معايرة عامة)، sources/scenarios.py (تعريف/جدولة/تأثيرات)، monitoring/evidence_rules.py (قواعد وحسابات وتصنيف)، tests/cr003/test_ms_simulation.py وtest_ms_diagnostics.py وtest_ms_integration_ui.py، audits/run_cr003_acceptance.py. المعدلة: sources/simulation.py؛ monitoring/event_detector.py وsimulation_evaluation.py؛ diagnostics/evidence.py وhypotheses.py وreports.py؛ ui/worker.py وmain_window.py وlocalization.py؛ README وهذا الملف. لا حزم جديدة، ولا تغييرات في source Serial/Replay/history أو Firmware أو models/Session/Recorder/Storage.

أوامر التشغيل الفعلية من C:\doccar:

```powershell
.\.venv\Scripts\python.exe -m pytest -c desktop/pyproject.toml desktop/tests audits/test_m1_acceptance.py -q --basetemp=data/cr003-final-verified --junitxml=docs/evidence/dc-cr-003/final.xml
.\.venv\Scripts\python.exe -m ruff check desktop/src desktop/tests/cr003 audits/run_cr003_acceptance.py
.\.venv\Scripts\python.exe -m ruff format --check desktop/src desktop/tests/cr003 audits/run_cr003_acceptance.py
.\.venv\Scripts\python.exe -m mypy desktop/src --config-file desktop/pyproject.toml
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe audits/run_cr003_acceptance.py
```

الاختبارات وE2E exit0؛ تفاصيل الجودة في `quality.log`. قيود باقية: كشف غير شامل كما في الحالات الخمس، لا تعميم على محركات حقيقية، لا Fuel Pressure/Misfire counters/بيانات غير مسجلة، لا ML/XAI، لا تحقق HIL/DPI متعدد/قارئ شاشة، وA07 وESP-IDF/اللوحة خارج النطاق. حالات المتطلبات الخمسة Completed تخص هذا النطاق الوظيفي فقط؛ لا تعني كشف جميع الاضطرابات أو اكتمال M1 العتادي.

### DC-CR-002 — Baseline / Impact Analysis (سجل سابق)

طلب تغيير مأذون: المحاكاة المضبوطة بثلاثة أوضاع، تاريخ جهاز برمجي، فحص المصادر، تنظيم مركز المصادر، ولغة/مظهر محفوظان. التنفيذ داخل M1؛ لا AI أو CAN أو تغيير Firmware.
خط الأساس أُعيد تشغيله قبل أي تعديل: `python -m pytest -c desktop/pyproject.toml desktop/tests audits/test_m1_acceptance.py -q --basetemp=data/cr002-baseline-tests --junitxml=docs/evidence/dc-cr-002/baseline.xml`؛ النتيجة **71 passed / 6 failed / 0 skipped** في 14.07s، exit 1. الأدلة baseline.log/xml في `docs/evidence/dc-cr-002/`. اختبارات القبول القديمة وFirmware محفوظة ببصمات `protected-before.json` ولن تعدل.

الأثر والعلاقات: SimulationSource → Session → validator/detector → EventRecorder/RingBuffer → SQLite؛ ProtocolReceiver → ProtocolSource → Session يستورد الأحداث؛ BackendWorker يملك المصدر وSQLite، وMainWindow يعرض الإشارات. سيضاف جدول حقن مستقل لا يدخل في trigger/evidence، ويعاد استخدام المسجل الحالي لتوليد تاريخ اختبار ثم نقل الحدث عبر JSONL v1 قبل التخزين في قاعدة التطبيق نفسها.

| المجال | الملفات المتوقع تعديلها/إضافتها | سبب التغيير وحد التوافق |
| --- | --- | --- |
| Simulation | sources/simulation.py، sources/faults.py (جديد)، core/session.py | NORMAL/FAULT_INJECTION/RANDOM_FAULTS وجدول Seed؛ الإبقاء على سيناريوهات/CLI M1 القديمة |
| Recording/history | monitoring/event_recorder.py، protocol/simulator.py، sources/device_simulator.py (جديد)، storage/sqlite_repository.py | مسجل واحد، تاريخ مولد يمر بالمحلل، وتمييز الأصل؛ توسعة متوافقة لنفس DB |
| Contracts/protocol | core/models.py، core/interfaces.py، protocol/receiver.py | إصلاح A02/A03/A04/A05 اللازمة لصحة فحص الملفات والتاريخ، دون تغيير wire v1 |
| Connection | sources/replay.py، sources/serial_device.py، ui/worker.py | فحص مصدر مرتبط بعقده وإغلاق منافذ؛ إصلاح A01/A06؛ لا Connectivity Service ولا فتح تلقائي |
| UI/settings | ui/main_window.py، ui/localization.py (جديد)، diagnostics/reports.py | حقول حسب المصدر، AR/EN وLight/Dark بـQSettings، عرض متوافق للتقارير القديمة |
| Verification/docs | tests جديدة تحت desktop/tests/cr002، README.md، هذا الملف | AT-001..015 + regression + E2E، دون تعديل اختبارات القبول القديمة |

| المتطلب | المرحلة | الحالة الحالية | دليل القبول |
| --- | --- | --- | --- |
| SIM-001 | B | Completed | AT-001 + original normal tests |
| SIM-002 | B | Completed | AT-002/005 + مكتبة الحقن |
| SIM-003 | B | Completed | AT-003/004 وجدول مستقل عن سرعة العرض |
| REC-001 | C | Completed | نافذة حدث 60..65، نهاية عند T+30 واستعادة |
| HIST-001 | D | Completed | AT-006..009 والتكرار/إعادة الرفع |
| DIAG-001 | C/D | Completed | نفس قواعد M1 بلا ground-truth leakage |
| UI-001 | E | Completed | AT-010 حقول وإعدادات معزولة حسب المصدر |
| CONN-001 | E | Completed | AT-011 وفشل/مهل fake USB بلا جهاز فعلي |
| SETTINGS-001 | F | Completed | AT-012/013 + جميع الصفحات |
| REG-002 | G | Completed | AT-014/015 + Ruff/mypy/E2E |

مخاطر محددة: تضارب حقن نفس الحساس يعالج برفض التركيبات المتعارضة؛ التاريخ بهويات مستقرة ومصدر اصطناعي صريح؛ قبول metadata الاستقبال المتغيرة لا يسمح بتغيير قياس ثابت؛ ترجمة الواجهة لا تغير سجلًا تاريخيًا. A07 خارج التعديل لأنه في Firmware المحظور تغييره؛ يبقى مفتوحًا وغير متحقق البناء.

### DC-CR-002 — Acceptance Traceability والنتائج الفعلية

مسارات الاختبارات التالية تحت `desktop/tests/cr002/`. كل صف **PASS في نطاق الاختبار الموضح**؛ USB وهمي ولا يمثل لوحة أو مركبة. دليل التشغيل المجمع `evidence/dc-cr-002/final.log/xml`، وتجربة الواجهة `e2e.log/json`.

| الاختبار | النتيجة | التنفيذ والدليل |
| --- | --- | --- |
| AT-001 | PASS | test_simulation: رحلة NORMAL كاملة بلا trigger؛ اختبارات normal الأصلية |
| AT-002 | PASS | test_cr002_recording: حقن60..65s، كشف63s،33..93s واستعادة؛ GUI301 عينة |
| AT-003 | PASS | test_simulation: دورات30/60/90/120؛ random-10x.json وrandom-30x.json تحفظ الجدول ونتائج الكشف |
| AT-004 | PASS | نفس Seed73/الإعدادات يطابق كل القراءات والجدول؛ تجربة فعلية عند10× و30× من GUI |
| AT-005 | PASS | اختبار حرارة+جهد+MAF، رفض كتابة الحساس نفسه، خللا العرض لا يولدان تشخيصًا مخترعًا |
| AT-006 | PASS | test_cr002_history وGUI: حدثان من جلسات سابقة عبر JSONL/receiver/Session/DB، عرض HISTORICAL |
| AT-007 | PASS | تاريخ الحرارة33..93s والجودة30..90s؛ كلاهما61 عينة عند1s وCOMPLETE |
| AT-008 | PASS | إعادة الاتصال والرفع الكامل مرتين: الحدثان بهوياتهما دون ازدواج؛ وقف تجميع ناقص لا يحفظ حدثًا |
| AT-009 | PASS | اختبار bootين في قراءة واحدة يحتفظ بعينتين وجلساتهما؛ اختبار القبول A04 القديم؛ لا فقد صامت |
| AT-010 | PASS | test_cr002_ui_settings: حقول المصدر ووسائطه فقط، USB بلا speed/seed، قفل المصدر مع تشغيل واحد |
| AT-011 | PASS | test_cr002_connections: منفذ وهمي يفتح/يغلق مرة، HELLO/caps/sample، timeout/version/units/unplug؛ ملفات schema مقابل handshake؛ فحص Replay من GUI |
| AT-012 | PASS | QSettings يعيد Dark؛ native settings-en-dark.png وreport-after-restart-en-dark.png |
| AT-013 | PASS | EN/LTR بعد إعادة الفتح؛ كل صفحات الواجهة مترجمة؛ التقرير العربي في DB مطابق دون تعديل |
| AT-014 | PASS | 71 أصلية + اختبار export→Replay→Session→event→report كامل + ترقية DBv1 مع تقرير مطابق + Legacy89s في GUI |
| AT-015 | PASS | اختبارات audits الستة نفسها نجحت بعد أن كانت6 فاشلة في baseline؛ بصماتها لم تتغير؛ A07 ملاحظة C مفتوحة |

بوابات المراحل: A خط الأساس71/6؛ B المحاكاة والأساس30 ناجحة؛ C التسجيل والتكامل31؛ D التاريخ والبروتوكول والتكامل36؛ E قبول GUI القديم+audit14 ثم اتصالات وهمية9؛ F إعدادات وصفحات2؛ G التشغيل المجمع النهائي أدناه. لم تُخفَ إخفاقات سابقة بـxfail ولم تُعدّل اختبارات القبول القديمة.

الأوامر الفعلية من `C:\doccar`:

```powershell
.\.venv\Scripts\python.exe -m doctorcar --help
.\.venv\Scripts\python.exe -m pytest -c desktop/pyproject.toml desktop/tests audits/test_m1_acceptance.py -q --basetemp=data/cr002-final-acceptance --junitxml=docs/evidence/dc-cr-002/final.xml
.\.venv\Scripts\python.exe -m ruff check desktop/src desktop/tests/cr002 audits/run_cr002_acceptance.py
.\.venv\Scripts\python.exe -m ruff format --check desktop/src desktop/tests/cr002 audits/run_cr002_acceptance.py
.\.venv\Scripts\python.exe -m mypy desktop/src --config-file desktop/pyproject.toml
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe audits/run_cr002_acceptance.py
```

نتائج exit الفعلية والأوقات مسجلة في final.log/xml وquality.log وe2e.log. خطأ تسمية ملف اختبار جديد صُحح قبل استكمال المرحلة C. خلال التطوير ظهر تعارض تمرير Event بدل ملخص dict للتقييم، وتوقيت رفض Replay أثناء connect كسر اختبارًا قديمًا؛ أصلح السبب في worker، وأُبقي رفض الملف عند القراءة مع verify مستقل. لا إخفاقات متبقية في التشغيل النهائي. محاولة برنامج تجربة CR الأولى انتظرت Replay بزمنه العادي بمهلة40s؛ سجلها محفوظ، والتجربة النهائية تفحصه وتشغله وتوقفه صراحة، والاختبار الجديد يغطي Replay كاملًا دون انتظار العرض.

## B. Requirements Baseline

معاني الحالة: Planned لم ينفذ، Partial نُفّذ جزء أو ينقص دليل، Completed تنفيذ مع دليل قبول فعلي، Deferred خارج M1. الأولوية Must ما لم يذكر غيرها.

| ID | النوع | المتطلب القابل للاختبار | المكوّن | المرحلة | الأولوية |
| --- | --- | --- | --- | --- | --- |
| FR-001 | FR | واجهة مصدر موحدة للمحاكاة وReplay والنقل التجريبي، بلا اتصال سيارة تلقائي | sources/session | M1 | Must |
| FR-002 | FR | سجل مركزي لـ11 قراءة رقمية وDTC تشخيصي، مع الوحدات والدعم والغياب | sensor_registry | M1 | Must |
| FR-003 | FR | محاكاة زمنية مترابطة لبدء/إحماء/خمول/تسارع/سير/تباطؤ/توقف وسيناريو غير طبيعي | simulation | M1 | Must |
| FR-004 | FR | تحقق البنية والوحدة والزمن والعمر والتسلسل والتكرار والمصدر مع حفظ الخام | data_quality | M1 | Must |
| FR-005 | FR | نافذة 30s قبل/بعد الحدث وفق أزمنة العينات، تداخل واستعادة بلا تكرار | recorder/storage | M1 | Must |
| FR-006 | FR | قواعد تجريبية حرارية وجودة بيانات، وتقرير يفصل الأدلة والفرضيات والقيود | detector/diagnostics | M1 | Must |
| FR-007 | FR | عقد فرضيات قابل للتوسع دون اختلاق كتالوج 80 عاملًا أو 68 حالة | hypotheses/docs | M1/M4 | Must |
| FR-008 | FR | عقود إدخال/خرج تحليل؛ تدريب وتقييم ML في M2 فقط | interfaces | M1/M2 | Must |
| FR-009 | FR | تفسير XAI بعد نموذج متحقق منه، دون إثبات سببي | backlog | M3 | Must |
| FR-010 | FR | PySide6 عربية RTL: تحكم ومصادر وحساسات وأحداث وتقرير وإعدادات دون تجميد | ui | M1 | Must |
| FR-011 | FR | مشروع ESP-IDF مستقل ESP32-S3، CAN/MicroSD غير مدّعى تنفيذهما | firmware | M1/M5 | Must |
| FR-012 | INT | JSON Lines v1 موحد، حجم وبنية وتسلسل وإعادة اتصال وأجزاء سليمة واستيراد idempotent | protocol | M1 | Must |
| FR-013 | FR | Firmware يولد بيانات TEST وHELLO/CAPABILITIES/SAMPLE/HEARTBEAT ويعالج خطأ أساسيًا | firmware | M1 | Must |
| SAF-001 | SAF | غياب أوامر السيارة والتفليش والاتصال التلقائي في M1 | desktop/firmware | M1 | Must |
| DATA-001 | DATA | فصل source/session/time/quality، DTC ليس حساسًا رقميًا وFreeze Frame منفصل | models | M1 | Must |
| DATA-002 | DATA | SQLite معاملات ومفاتيح فريدة واسترجاع بعد إغلاق ونوافذ جزئية موصوفة | storage | M1 | Must |
| NFR-001 | NFR | مصدر وجلسة واحدان، worker خارج GUI وإغلاق سليم وأخطاء مرئية | session/ui | M1 | Must |
| NFR-002 | NFR | تثبيت حزمة وتشغيل من بيئة محلية مع اعتماديات مفصولة وإصدارات مثبتة مسجلة | packaging | M1 | Must |
| TEST-001 | TEST | وحدات وتكامل وE2E-01..08 وRuff وmypy وأدلة فعلية | tests | M1 | Must |
| TEST-002 | TEST | فحص بناء ESP-IDF إن توفر، وتوثيق عدم التحقق إن غاب، دون تفليش | firmware | M1 | Must |

## C. Requirements Traceability Matrix

المصفوفة الحالية بعد DC-CR-003؛ تبقى حالات M1 الأصلية15/4/1 والطلبات الخمسة MS مكتملة في قسمها أعلاه. الأدلة الأحدث في evidence/dc-cr-003/final.xml وe2e.json؛ M أدناه يحتفظ بنتيجة التدقيق السابقة بوصفها تاريخًا. Completed يخص السلوك المحدد ولا يثبت جهازًا فعليًا.

| المتطلب | المكوّن والتنفيذ | اختبار القبول | الحالة | الدليل الفعلي |
| --- | --- | --- | --- | --- |
| FR-001 | core/interfaces.py, core/session.py, sources/*.py | foundation replay + pipeline + device_source + fake serial | Completed | acceptance-audit/pytest.xml؛ عُقد المسار الموحد تعمل في النطاق المختبر؛ عيوب نقل الحالات الحدية في FR-012 |
| FR-002 | core/sensor_registry.py, sources/replay.py | test_registry + audit test_fr002_replay_must_not_advertise_explicitly_unsupported_sensor | Completed | A01 Fixed؛ الاختبار القديم للقراءة UNSUPPORTED ناجح؛ final.xml |
| FR-003 | sources/simulation.py | deterministic_time_dependent_correlated_simulation؛ E2E-01/02؛ تجربة GUI جديدة | Completed | acceptance-audit/pytest.xml وe2e.json؛ قراءات زمنية فعلية من المحاكي |
| FR-004 | monitoring/data_quality.py, models.py, sources/replay.py | bad types/units/missing/age/order/gaps + audit boolean contract version | Completed | A02 Fixed؛ رفض boolean version مع اختبارات الوحدات والتسلسل والعمر؛ final.xml |
| FR-005 | ring_buffer.py, event_recorder.py, sqlite_repository.py | irregular buffer، overlap/reopen، interruption؛ تجربة GUI/SQL جديدة | Completed | acceptance-audit/e2e.json: كشف 89000ms ونافذة 59000..119000ms و301 عينة؛ A04 عولج في DC-CR-002 |
| FR-006 | event_detector.py, diagnostics/*.py, ui/worker.py | thermal/quality/evidence الأصلية + audit export error | Completed | A06 Fixed؛ خطأ التصدير مع مصدر سليم لا يولد CONNECTION؛ final.xml وe2e.json |
| FR-007 | diagnostics/hypotheses.py | missing_contradictory_evidence؛ report pipeline | Completed | acceptance-audit/pytest.xml؛ عقد Hypothesis ومنطقه المحدود موجودان؛ الكتالوج البحثي مؤجل M4 |
| FR-008 | core/interfaces.py: WindowAnalyzer + analysis/* | عقد + CR004/CR005 (تدريب، تقييم، ربط) | Completed (محاكاة) | محدّث في DC-CR-005: النموذج موجود وتقييم Rules/ML/Combined على مستوى النافذة والحدث؛ الأداء من مولد اصطناعي فقط |
| FR-009 | analysis/explanation.py | test_xai + test_report_ai | Completed (محاكاة، غير SHAP) | محدّث في DC-CR-005: استبدال مرجعي لمجموعات ميزات يعيد حساب درجة النموذج؛ لا سببية ولا نسب ثقة |
| FR-010 | ui/main_window.py, ui/worker.py | integration/test_ui؛ E2E-08؛ تجربة native كاملة جديدة | Completed | acceptance-audit/e2e.json وe2e-report-after-restart.png؛ عرض التقرير واستعادته نجحا؛ A06 في NFR-001 مصحح الآن |
| FR-011 | firmware/CMakeLists.txt وmain/*.c | مراجعة C وCMake وفحص SDK الحالي | Partial | acceptance-audit/environment.json؛ لا idf.py في PATH؛ لم يبنَ المصدر |
| FR-012 | protocol/*.py وschema، sources/serial_device.py | الاختبارات الأصلية + audit boot transition/live sample then upload | Partial | A04/A05 Fixed مع اختباراتهما القديمة والتاريخ المتكرر؛ A07 في استقبال C غير المعدل يبقي التوافق العتادي غير متحقق |
| FR-013 | firmware/main/main.c, test_data.c, device_protocol.c | مراجعة ثابتة لمسارات الإرسال والتوليد والاستقبال | Partial | acceptance-audit/firmware-review.json؛ كود فعلي وبنية إرسال متسقة بالقراءة، لكن لا build/byte-level test؛ استقبال C لا يتحقق من كل حقول الغلاف |
| SAF-001 | أنواع رسائل محدودة، لا OBD backend، CAN compile guard | رفض CLEAR_DTC/REAL، لا auto-connect، مراجعة C بلا أوامر مركبة | Completed | acceptance-audit/pytest.xml وe2e.json؛ لم تفتح هذه المراجعة منفذًا أو مركبة ولم تفلش جهازًا |
| DATA-001 | models.py، provenance وdtc_quality | roundtrip + audit boolean version/inconsistent event end | Completed | A02/A03 Fixed؛ نسخة int وعلاقة نهاية الحدث مطابقة؛ final.xml |
| DATA-002 | storage/sqlite_repository.py | atomic conflict، finalized immutability، future schema، crash/reopen؛ SQL integrity | Completed | acceptance-audit/pytest.xml وe2e.json؛ المعاملات والقيود والاستعادة مثبتة؛ A05 عولج مع اختبار تعارض قياس حقيقي |
| NFR-001 | Session + BackendWorker واحد؛ commands queue | navigation/duplicate start/close + audit export error | Completed | A06 Fixed؛ بقاء مصدر سليم عند خطأ export، قفل المصدر وفحص/إغلاق الموارد؛ final.xml |
| NFR-002 | desktop/pyproject.toml + requirements-lock.txt | تثبيت Wheel في data/acceptance-audit-venv الجديدة، مطابقة ملفات Wheel بالمصدر، -I import/schema، native Qt/pip check | Completed | acceptance-audit/package.log؛ دليل تثبيت تاريخي قبل CR؛ لم يُعد إنشاء Wheel بعد هذا التغيير؛ التشغيل الحالي editable ومتحقق بالاختبارات وQt |
| TEST-001 | unit/integration/e2e + audits/*.py | إعادة الاختبارات وفحوص الجودة وتوثيق نتائج القبول الإضافية | Completed | dc-cr-003/final.xml:138 ناجحة وصفر فشل/تخطي؛ quality.log ناجح؛ اكتمال نشاط التحقق لا يعني نجاح كل معايير قبول M1 |
| TEST-002 | فحص توفر SDK وتوثيق الاستثناء | idf.py/cmake/ninja غير متاحة في PATH حاليًا | Completed | acceptance-audit/environment.json؛ هذا توثيق عدم تنفيذ البناء، وليس نجاحه |

المجموع الحالي: **20 متطلبًا: 15 Completed، و4 Partial، و1 Deferred**. الجزئية FR-008 وFR-011 وFR-012 وFR-013؛ المؤجل FR-009. خمس حالات عادت Completed بعد دليل الإصلاح، وFR-012 ما زال Partial بسبب A07 والعتاد.


## D. System Architecture

مصدر واحد → DataQuality → Measurement stream داخل Session → عرض حي + RingBuffer → Detector → Recorder → SQLite → Evidence → Report.
UI تتلقى snapshots وإشارات من worker، ولا تنشئ قارئًا أو قاعدة تشخيص. Repository ملك الخيط الذي أنشأه. لا خادم ولا Backend ثانٍ.
العقود: sample v1، الزمن `timestamp_ms` رتيب نسبي للجلسة، `received_at_ms` وقت استقبال المضيف، و`source` مستقل عن transport. Replay يحفظ provenance الأصلي ويمنح جلسة تشغيل جديدة. النافذة تعتمد زمن العينة، وتسريع العرض لا يغيره.

## E. File Registry

**ملفات DC-CR-004/005 (analysis وغيرها):** analysis/windows.py (نوافذ سببية 47 ميزة)، analysis/model.py (تحميل موثق للنماذج المحزومة)، analysis/analyzer.py (DetectionPolicy/PersistenceGate/AnomalyAnalyzer)، analysis/explanation.py (XAI)، analysis/status.py (حالات AI ورسائلها)، analysis/benchmark.py (dataset-3 وتدريب v2 وتقييم الحدث)، analysis/experiment.py (v1 التاريخي)، analysis/models/{cr004-iforest-v1,cr005-iforest-v2}/، diagnostics/human_report.py (تقرير مبسط/فني)، sources/network_device.py، protocol/network_simulator.py، ui/timeseries_plot.py، audits/verify_installed_package.py، desktop/tests/cr005/*.

جميع مسارات Python التالية تحت `desktop/src/doctorcar/`. «متحقق» يعني السلوك المحلي المحدد في الاختبارات فقط؛ القبول الرسمي في C وملاحظات التدقيق في M. لا تعني نتيجة اختبار إيجابي خلو المكون من العيوب المكتشفة أدناه. الحالة C غير مبني تخص Firmware.

| الملف | المسؤولية | يستدعي | يستدعيه | الحالة/ملاحظة |
| --- | --- | --- | --- | --- |
| __init__.py | إصدار الحزمة 0.1.0 | — | package/import | متحقق بتثبيت Wheel |
| __main__.py | CLI وإعداد logging وتشغيل Qt | MainWindow | python -m doctorcar / entrypoint | متحقق --help وnative startup |
| core/models.py | Reading/Sample/Trigger/Event والتحويل | dataclasses/typing | جميع الطبقات | متحقق؛ A02/A03 مصححان مع اختبارات القبول القديمة |
| core/interfaces.py | DataSource/Capabilities/WindowAnalyzer | models | sources/session | متحقق types؛ تنفيذ ML في analysis/ (DC-CR-004/005) |
| core/sensor_registry.py | سجل وحيد للأسماء والوحدات | SensorSpec | quality/sources/UI | متحقق |
| core/session.py | تنسيق المسار الوحيد والجلسات والإغلاق | source/quality/detector/recorder/repo | worker/tests/scripts | متحقق |
| sources/simulation.py | محاكاة زمنية مترابطة | models/registry | Session/device simulator | متحقق seed وسيناريوهات |
| sources/replay.py | قراءة samples JSONL وإغلاق الملف | models | Session/worker | متحقق؛ verify وقدرات مصدر فعلية ورفض boolean؛ A01/A02 مصححان |
| sources/serial_device.py | Serial صريح وProtocolFileSource | pyserial/ProtocolReceiver | Session/worker | متحقق بملف وfake port؛ لا منفذ فعلي |
| monitoring/data_quality.py | وحدات وجودة وتسلسل وعمر | registry/models | Session | اختبارات القيمة والوحدة والعمر ناجحة؛ حد إدخال Replay مصحح في A02؛ bounds تجريبية فقط |
| monitoring/ring_buffer.py | نافذة زمنية deque | Sample | EventRecorder | متحقق بتوقيت غير منتظم |
| monitoring/event_detector.py | قاعدتا thermal/data quality | Trigger | Session | متحقق؛ لا حدود سيارة عامة |
| monitoring/event_recorder.py | قبل/بعد/تداخل/checkpoint/partial | TimeRingBuffer/repo | Session | متحقق |
| storage/sqlite_repository.py | SQL ومعاملات واستعادة وتصدير | sqlite3/models | Session/worker/recorder | متحقق؛ connection ملك خيط واحد |
| diagnostics/evidence.py | تلخيص الأدلة الصالحة | Event/Quality | reports | متحقق؛ لا حرارة مخترعة |
| diagnostics/hypotheses.py | عقد فرضيات وأسباب بديلة محدودة | Evidence | reports | متحقق؛ لا كتالوج 68 |
| diagnostics/reports.py | عرض AR/EN؛ التقرير العربي الأصلي محفوظ مع حد الترجمة | evidence/hypotheses | worker/scripts | متحقق؛ ضبط اتجاه القيم داخل RTL |
| protocol/device_protocol_v1.schema.json | مخطط وحيد مضمن في Wheel | — | codec؛ مدخل schemas/ | التحقق الفعلي من كل رسالة |
| protocol/codec.py | UTF-8/JSONL/version/schema/size | jsonschema/resources | receiver/simulator | متحقق |
| protocol/messages.py | إنشاء الغلاف المشترك | — | simulator/tests | متحقق عبر codec |
| protocol/receiver.py | framing/handshake/sequence/chunk SHA256 | codec/models | ProtocolSource | متحقق محليًا؛ A04/A05 مصححان؛ A07 العتادي خارج هذا الملف |
| protocol/simulator.py | جهاز برمجي ورفع أحداث مجزأة | SimulationSource/codec | CLI/tests | متحقق؛ SIMULATION دائمًا |
| ui/worker.py | أوامر وإشارات وخيط مصدر/SQLite | Session/sources/reports | MainWindow | متحقق؛ create_source وفحص/منافذ وعزل أخطاء أوامر محلية؛ A06 مصحح |
| ui/main_window.py | ست صفحات AR/EN وRTL/LTR وLight/Dark | worker/registry | __main__/preview/tests | متحقق بصريًا native وoffscreen سلوكيًا |
| core, sources, monitoring, diagnostics, protocol, storage, ui / __init__.py | تهيئة حزم Python بحدود واضحة | — | مستورد الحزمة | ملفات تهيئة، ليست وظائف صورية |
| desktop/pyproject.toml | بناء واعتماديات وأدوات | setuptools | pip/pytest/Ruff/mypy | متحقق |
| desktop/requirements-lock.txt | إصدارات البيئة المقاسة كـconstraints | — | pip -c | لا AI dependencies |
| desktop/tests/unit/test_foundation.py | نماذج ومحاكاة وReplay وجودة | core/sources/quality | pytest | 16 حالة |
| desktop/tests/unit/test_recording.py | نافذة وتداخل وSQL واستعادة | recorder/storage | pytest | 8 حالات |
| desktop/tests/unit/test_protocol.py | malformed/handshake/chunks/fake Serial | protocol/sources | pytest | 30 حالة |
| desktop/tests/integration/test_pipeline.py | المصدر إلى التقرير والفشل والعمر | Session/reports | pytest | 7 حالات |
| desktop/tests/integration/test_device_source.py | ملف جهاز وأحداث مرفوعة إلى المسار المشترك | ProtocolFileSource/Session | pytest | حالتان؛ تطبيع جودة العينات المستوردة |
| desktop/tests/integration/test_ui.py | RTL وتنقل وإغلاق وفشل التخزين | MainWindow | pytest | حالتان |
| desktop/tests/e2e/test_acceptance.py | E2E-01..08 | التطبيق والمكونات نفسها | pytest | 8 حالات |
| scripts/run_e2e.py | تجربة محلية وأدلة فعلية | Session/repo/protocol | المستخدم/التحقق | متحقق؛ DB جديدة داخل data/ |
| scripts/preview_ui.py | صور Qt حقيقية دون عرض نافذة المعاينة | MainWindow/native Windows | المستخدم/التحقق | متحقق؛ لا screenshot خارجي |
| audits/test_m1_acceptance.py | ستة اختبارات قبول مستقلة لإعادة إنتاج عيوب M1 | العقود والمصادر وworker | pytest أثناء التدقيق | 6 ناجحة بعد الإصلاح؛ الملف نفسه لم يعدل ولا xfail |
| audits/run_m1_acceptance.py | تجربة GUI جديدة وفحص SQL وإعادة فتح التقرير | MainWindow وsqlite3 مباشرة | التدقيق/المستخدم | ناجحة؛ دليل منفصل عن تجربة التنفيذ الأولى |
| firmware/CMakeLists.txt | مشروع ESP-IDF واستهداف s3 | IDF build system | idf.py build | C غير مبني |
| firmware/sdkconfig.defaults | console UART وUSB protocol defaults | Kconfig | ESP-IDF | غير متحقق على SDK |
| firmware/main/CMakeLists.txt | تسجيل C واعتماديات json/USB/timer | IDF components | root CMake | غير مبني |
| firmware/main/Kconfig.projbuild | اختيار السيناريو الحراري الاختباري | — | sdkconfig | غير مبني |
| firmware/main/main.c | app_main وboot/session والتوقيت وUSB | protocol/test_data/ESP-IDF | FreeRTOS startup | مصدر وظيفي؛ غير مبني/غير مفلش |
| firmware/main/test_data.c/.h | بيانات اختبار مترابطة مع الزمن | math/cJSON | main.c | لا CAN أو SD |
| firmware/main/device_protocol.c/.h | JSONL v1 وإعلان القدرات وخطأ/ACK/HELLO | cJSON/USB driver | main.c | event_upload=false؛ غير مختبر فعليًا |

الوثائق: README أوامر التشغيل؛ هذا الملف الحالة الرسمية؛ DEVICE_PROTOCOL.md مواصفات تقنية؛ schemas/ مدخل مخطط محلي؛ `data/` وبيئات Python ومخرجات build مؤقتة ومتجاهلة في Git، ولا تمثل نظمًا تطبيقية إضافية.

ملفات DC-CR-002 المضافة: sources/faults.py (تعريف/جدولة/تطبيق حقن)، sources/device_simulator.py (تاريخ EventRecorder ثم JSONL v1)، monitoring/simulation_evaluation.py (مقارنة اختبار لاحقة)، ui/localization.py (ترجمة عرض فقط)، خمسة ملفات اختبار cr002 (30 حالة)، audits/run_cr002_acceptance.py (تجربة Qt وأدلة).
الملفات المعدلة فعلًا: core/models.py/interfaces.py/session.py، sources/simulation.py/replay.py/serial_device.py، monitoring/event_recorder.py، protocol/receiver.py، storage/sqlite_repository.py، diagnostics/reports.py، ui/worker.py/main_window.py، README وهذا الملف. لم تتغير اختبارات القبول القديمة أو أي ملف Firmware. protocol/simulator.py أعيد استخدامه دون تغيير وظيفته أو CLI.

## F. Functions & Interfaces Registry

| الكلاس/الواجهة | المدخلات → المخرجات | الاستثناءات والعلاقات |
| --- | --- | --- |
| Reading / Sample.from_dict,to_dict | قيمة/وحدة/هوية/وقت → sample v1 | ValueError/KeyError للمدخلات الخاطئة؛ Quality صريحة |
| SensorRegistry.register_sensor,get,get_supported_sensors | spec أو IDs دعم → specs | ValueError للتكرار، KeyError لمعرف غير مسجل |
| DataSource.connect,start,read_measurements,stop,disconnect | إعداد مصدر → Sample أو None | read غير حاجب؛ None قد تعني انتظارًا أو EOF مع exhausted |
| DataSource.get_capabilities,get_connection_state | — → قدرات/حالة | لا افتراض دعم مركبة |
| DataSource.drain_events,get_current_timestamp_ms | — → أحداث نهائية/ساعة مصدر اختيارية | نفس المسار المشترك؛ Replay لا يقاس بعمر ساعة المضيف |
| SimulationSource | scenario/seed/step/duration → samples زمنية | ValueError للتكوين؛ connect يعيد الجلسة وRNG |
| ReplaySource / ProtocolFileSource | Path → stream | OSError/ValueError للملف أو التوقيت/التأطير؛ disconnect يغلق الملف |
| SerialDeviceSource | منفذ صريح أو port_factory اختباري → test stream | SerialException/TimeoutError/ValueError؛ لا write أو scan |
| DataQualityValidator.validate_measurement | Sample وnow_ms اختياري → ValidationResult | accepted=false للتكرار/التراجع؛ raw قبل التصحيح محفوظ |
| Session.start,step,stop,record_connection_loss | source/repo → stream موحد/حفظ | أخطاء I/O تنتقل للـworker؛ stop يحرر المصدر حتى عند فشل checkpoint |
| TimeRingBuffer.append_measurement,get_pre_event_window | Sample/time → آخر 30s | ValueError لخلط جلسات أو تراجع الزمن |
| EventDetector.evaluate_trigger | Sample/issues → tuple Trigger | نسخة demo-rules-1.0؛ لا DTC شرطًا للكشف |
| EventRecorder.append_measurement,start_event,finalize_event,stop | stream/triggers → أحداث/checkpoints | UUID5 مستقر للجلسة/النوع/الوقت؛ إغلاق مبكر PARTIAL |
| SQLiteRepository.save_session,save_measurement,save_event | العقود → commit محلي | sqlite3.Error/OSError وValueError للتعارض/إصدار مستقبل |
| SQLiteRepository.get_event,list_events,export_session | ID أو Path → Event/rows/JSONL | لا إنشاء حدث نهائي مكرر؛ لا overwrite متعارض |
| build_evidence,evaluate_hypotheses,build_diagnostic_report | Event → Evidence/Hypothesis/text | نقص الأدلة ظاهر؛ لا نسب سببية |
| encode_message,decode_message,validate_protocol_version | envelope/bytes → JSONL/envelope | ValueError للنسخة/البنية/الحجم/JSON |
| ProtocolReceiver.feed,handle_message,validate_sequence,reset_connection | bytes → queues samples/events/errors | handshake، duplicate suppression، bounded chunks وSHA256 |
| BackendWorker.submit,run,shutdown | queue commands → Qt signals | queue محدودة؛ أخطاء مرئية؛ لا SQLite عابر للخيوط |
| MainWindow | signals/actions → صفحات عربية | لا قواعد تشخيص؛ closeEvent ينتظر worker بطريقة غير حاجبة |
| WindowAnalyzer.evaluate_window | tuple Sample → tuple Trigger | منفذ في AnomalyAnalyzer (analysis/analyzer.py) |
| dc_test_sample / dc_send / dc_announce / dc_poll_input | وقت/هوية/CJSON → USB JSONL أو خطأ | send يستهلك payload؛ ذاكرة وحدود حجم؛ لم ينفذ على العتاد |

## G. Data & Sensor Registry

RPM rpm؛ SPEED km/h؛ COOLANT_TEMP °C؛ ENGINE_LOAD %؛ THROTTLE_POS %؛ INTAKE_PRESSURE kPa؛ MAF g/s؛ INTAKE_TEMP °C؛ SHORT_FUEL_TRIM %؛ LONG_FUEL_TRIM %؛ CONTROL_MODULE_VOLTAGE V؛ DTC مجموعة تشخيصية.
الحالة لكل قراءة Available/Missing/Unsupported/Invalid/Stale. نطاقات plausibility للمحاكي سياق تجريبي لا مواصفات سيارة، والسجل لا يزعم دعم أي مركبة. المصدر SIMULATION أو DEVICE_TEST أو REPLAY مع provenance؛ لا REAL في M1. لكل سجل sensor_id وarabic_name وvariable وunit وkind وsource وvalid_range (غير محدد دون مواصفة موثوقة) وmissing_policy. الدعم يأتي من Capabilities لا من افتراض في السجل. DTC منفصل في `dtcs` و`dtc_quality`، وFreeze Frame اختياري مستقل. M1 لا يولد ECU Freeze Frame.

## H. OBD Diagnostic Scope

M1 لا يقرأ سيارة ولا يستخدم python-OBD. المستهدف لاحقًا الخدمات القياسية الموثقة للبيانات الحية وDTC وFreeze Frame بحسب دعم المركبة. لا مسح ولا كتابة ولا تشغيل مشغلات. Passive CAN مختلف عن Active Read-Only OBD؛ لا يُنفذ أيهما الآن. النافذة المسجلة ليست ECU Freeze Frame؛ حالة الأخير غير متاح في M1، ولا يختلق زمنه.

## I. Firmware & Hardware Interface

ESP32-S3 DevKitC-1؛ ESP-IDF 5.5.x مستهدف، وراجعت الواجهات مقابل المصدر الرسمي v5.5.1. USB Serial/JTAG عبر موصل USB الأصلي المناسب، JSONL منفصل عن console UART. Real CAN معطل وغير منفذ. Classical CAN فقط عبر TWAI وtransceiver؛ CAN FD غير مدعوم داخليًا. CAN transceiver ليس OBD interpreter؛ ISO-TP عند الحاجة في مرحلة لاحقة.
MicroSD/SPI والجهد والطاقة والحماية والسكون وWi-Fi/BLE مؤجلة. لم يجر فتح منفذ COM أو تفليش جهاز أو توصيل مركبة. أدوات `idf.py` وCMake وNinja وclang وgcc غير موجودة في PATH وفق evidence/environment.json؛ **لم يُشغل بناء Firmware**. لا ينسب نجاح محاكي Python إلى مخرجات C لم تُنفذ.
Firmware يولد دورة زمنية مترابطة كل 200ms، HELLO/CAPABILITIES كل 5s، HEARTBEAT كل 1s، session boot مختلفة، source=DEVICE_TEST. event_upload=false وCAN/SD=false. يستجيب HELLO بإعلان ويهمل ACK ويرسل ERROR للأخطاء الأساسية والأنواع غير المدعومة؛ لا أمر يغير المركبة. إصدارات C وPython والمخطط تستهدف v1 نفسه، لكن إثبات توافق بايتات جهاز فعلي مؤجل. تفاصيل الحجم وSHA256 وإعادة الرفع في [DEVICE_PROTOCOL.md](DEVICE_PROTOCOL.md).
**تدقيق المصدر الحالي:** الوصف السابق لما يقصده كود C وليس قياسًا لمخرجات جهاز. `main.c` يهيئ USB ويجدول الرسائل، و`test_data.c` يحسب بيانات مترابطة فعلًا، و`device_protocol.c` يسلسل cJSON ويعالج القراءة والحدود. بنية الإرسال ومعرفات القراءات والوحدات متسقة مع المخطط بالقراءة. لكن `handle_line` (الأسطر 104–118) يتحقق من object/version/type فقط؛ الغلاف الناقص `{"protocol_version":1,"type":"HELLO"}` يصل إلى إعلان المصافحة وفق مسار C، بينما يرفضه محلل Python. هذه ملاحظة ثابتة A07، وليست اختبار تنفيذ C. لا ادعاء بمطابقة كاملة للبروتوكول أو نجاح build/USB/لوحة. الأدوات غير متاحة في PATH في المراجعة الحالية أيضًا، كما في acceptance-audit/environment.json.

## J. Event Recorder Specification

RingBuffer زمني 30,000ms لكل جلسة، يحتفظ بالحدود الشاملة وفق timestamp_ms، لا بعدد الصفوف. trigger حراري تجريبي: ≥108°C لمدة 3000ms مع RPM>400 وبيانات صالحة من سياق اختبار، أو إخفاق جودة بيانات. هذه حدود demo وليست مواصفة أي مركبة.
الحدث يبدأ عند عينة الكشف، ويحفظ المتاح من السابق ويستمر 30,000ms. يحفظ أول trigger من النوع نفسه ضمن حدث نشط ولا ينشئ نسخة أخرى أو يمدد النافذة تلقائيًا؛ الأنواع المختلفة تتداخل مع إعادة استخدام مفتاح العينة. تستبعد العينة التالية إن تجاوزت نهاية النافذة ويحتفظ بالمتاح فقط. الإيقاف المبكر PARTIAL؛ الانقطاع المفاجئ يسترجع checkpoint كـPARTIAL مع سبب واضح. العينات محفوظة مرة واحدة في measurements مع روابط للأحداث. لا ضمان لالتقاط أسرع من الوصول، ولا ادعاء continuity في الفجوات.
قياس التجربة النهائية عند 1Hz: trigger=89000ms؛ start=59000ms؛ end=119000ms؛ 61 عينة. اختبار E2E عند 2Hz يحفظ 121 عينة لنفس نافذة 60 ثانية؛ واجهة المحاكي عند 5Hz تعرض وتحفظ العقد نفسه.

## K. Diagnostics & AI

**محدّث DC-CR-005:** ML (IsolationForest) وXAI موجودان ومربوطان بالأحداث سببيًا (انظر أعلى الملف). النص التالي تاريخي عن M1.

M1 قواعد تجريبية فقط. تقرير عربي يفصل Observation/Anomaly/Hypothesis/Evidence/Limitation/Recommended Check، دون نسبة ثقة ميكانيكية. ارتفاع حراري تجريبي لا يحدد ثرموستات أو مضخة. انقطاع النقل ليس عطل كهرباء مركبة. 80 عاملًا و68 فرضية أهداف بحثية غير معتمدة؛ القوائم الأصلية غير مقدمة، ولا نُكمل أعدادها بالتخمين. M2 يقارن نموذج السلاسل الزمنية بالقواعد مع منع التسرب؛ M3 XAI لا يثبت السببية.

## L. Database Schema

| الجدول | الأعمدة والمفاتيح | القيود |
| --- | --- | --- |
| sessions | session_id PK, source, started_at_ms, status | مصدر واحد لكل جلسة؛ started_at وقت استقبال مضيف لا تاريخ عطل |
| measurements | session_id FK, sequence_number, timestamp_ms, data_json | PK(session_id,sequence_number)، JSON يحتوي الجودة والوحدات وraw/provenance |
| events | event_id PK, session_id FK, trigger_ms, kind, status, metadata_json | metadata فيها trigger/version/reason/evidence/end/limitations دون نسخ samples |
| event_samples | event_id FK, session_id, sequence_number | PK للثلاثة، FK مركب إلى measurements؛ نفس العينة تخدم أحداثًا متداخلة |
| simulation_runs | session_id PK/FK, metadata_json | Seed/mode/step/duration/max_faults/probability/schedule_version/cycles/fault_schedule؛ اختبار لا دليل تشخيص |

`PRAGMA user_version=2`؛ يقبل 0/1/2 ويضيف simulation_runs في القاعدة نفسها دون إعادة كتابة السجلات، ويرفض المستقبل غير المعروف. foreign_keys وWAL وsynchronous=FULL مفعلة، والكتابة بمعاملات وSQL parameter binding. تثبت عينات الحدث تدريجيًا، وعند إعادة الفتح تتحول RECORDING إلى PARTIAL مع آخر checkpoint؛ ACTIVE sessions السابقة إلى INTERRUPTED. عند الإغلاق النظامي STOPPED. ملف واحد لا يستخدمه تطبيقان مسجلان بالتوازي؛ لا يوجد locking متعدد التطبيقات في M1. لا بيانات خاصة تُرسل خارجيًا.

## M. Test Plan & Evidence

**الحالي DC-CR-003:**138 passed، صفر فشل/أخطاء/تخطي؛72.08s، quality.log وe2e.json وsimulation-evaluation.json في evidence/dc-cr-003. AT-MS01..14 موثقة أعلى الملف، وحدود الكشف الخمس صريحة. السجلات التالية تاريخية.

**سجل DC-CR-002 السابق:** 107 passed / 0 failed / 0 skipped في 17.26s؛ final.log/xml وquality.log وe2e.json تحت evidence/dc-cr-002. الجدول والعيوب في التدقيق التالي سجل تاريخي قبل الإصلاح، ويتقدم عليه قسم CR الحالي وC وS.

### Acceptance Audit السابق — تاريخي، استُبدلت حالته بـDC-CR-002 أعلاه

الحكم **PARTIAL**. قرأت الكود والاختبارات والعقد وFirmware، ثم أعدت التنفيذ في أدلة منفصلة. لم أستخدم التقرير السابق لإثبات النجاح، ولم أصلح كود التطبيق أثناء التدقيق. ملفات الأدوات الجديدة تحت audits/ تختبر المنتج القائم فقط؛ لقطات hashes قبل/بعد في acceptance-audit تثبت بقاء ملفات المنتج الـ41 دون تغيير. [ملخص نتائج التدقيق](evidence/acceptance-audit/summary.json)، [بصمات المنتج قبل](evidence/acceptance-audit/product-before.json)، [بعد](evidence/acceptance-audit/product-after.json).

| التحقق الجديد | النتيجة الفعلية | الدليل الحالي |
| --- | --- | --- |
| حزمة الاختبارات الأصلية | 71 passed، 0 failed، 0 errors، 0 skipped، exit 0 | [pytest.log](evidence/acceptance-audit/pytest.log)، [pytest.xml](evidence/acceptance-audit/pytest.xml) |
| اختبارات القبول الإضافية | 6 failed، 0 errors، 0 skipped، exit 1؛ إخفاقات منتج موضحة أدناه | [probes.log](evidence/acceptance-audit/probes.log)، [probes.xml](evidence/acceptance-audit/probes.xml) |
| Ruff/format للمنتج والاختبارات الأصلية | ناجح؛ 39 ملفًا منسقًا | [quality.log](evidence/acceptance-audit/quality.log) |
| mypy strict / pip check | ناجح؛ 30 ملف source، لا اعتماديات مكسورة | quality.log |
| تجربة GUI أصلية جديدة | PASS للمسار الأساسي فقط؛ تشغيل thermal من الواجهة، حفظ الحدث، إغلاق/فتح التطبيق وعرض تقرير مطابق | [e2e.json](evidence/acceptance-audit/e2e.json)، [e2e.log](evidence/acceptance-audit/e2e.log)، [صورة التقرير بعد الفتح](evidence/acceptance-audit/e2e-report-after-restart.png)، [نص التقرير](evidence/acceptance-audit/e2e-report.txt) |
| SQL مستقل عن Repository | integrity_check=ok، لا مخالفات foreign_key_check؛ trigger=89000ms وwindow=59000..119000ms و301 عينة SIMULATION | e2e.json؛ قاعدة جديدة مسارها مثبت في الملف نفسه |
| إعادة تحقق التثبيت | بيئة جديدة data/acceptance-audit-venv؛ تثبيت Wheel ومطابقة بايتات Python/schema بالمصدر؛ import -I من site-packages وnative GUI startup/close ناجحان | [package.log](evidence/acceptance-audit/package.log) |
| Firmware | مصدر حقيقي؛ مراجعة بنية إرسال فقط؛ build/تشغيل C/USB/لوحة لم تنفذ؛ عيب تحقق استقبال ثابت | [firmware-review.json](evidence/acceptance-audit/firmware-review.json)، [environment.json](evidence/acceptance-audit/environment.json) |

الأوامر التي شغلت في هذه المراجعة من `C:\doccar`، والنتائج أعلاه تخصها:

```powershell
.\.venv\Scripts\python.exe -m pytest desktop/tests -q --basetemp=.audit-test-tmp --junitxml=docs/evidence/acceptance-audit/pytest.xml
.\.venv\Scripts\python.exe -m pytest -c desktop/pyproject.toml audits/test_m1_acceptance.py -q --basetemp=data/acceptance-audit-tests --junitxml=docs/evidence/acceptance-audit/probes.xml
.\.venv\Scripts\python.exe -m ruff check desktop scripts
.\.venv\Scripts\python.exe -m ruff format --check desktop scripts
.\.venv\Scripts\python.exe -m mypy --config-file desktop/pyproject.toml desktop/src/doctorcar
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -X utf8 audits/run_m1_acceptance.py
python -m venv data/acceptance-audit-venv
.\data\acceptance-audit-venv\Scripts\python.exe -m pip install -c desktop/requirements-lock.txt data/wheels/doctorcar-0.1.0-py3-none-any.whl
.\data\acceptance-audit-venv\Scripts\python.exe -m pip check
Get-Command idf.py,cmake,ninja,clang,gcc -ErrorAction SilentlyContinue
```

لا نُعامل exit 1 لاختبارات القبول كتعذر تشغيل؛ جميعها جمعت ونفذت وفشلت في السلوك المتوقع. SDK command lookup لا يعثر على الأدوات في PATH؛ لذلك لم يُشغّل idf.py build أصلًا ولا يوصف بأنه ناجح أو فاشل في البناء. الاختبارات الأصلية والإضافية شغلت منفصلتين: مجموع الحالات المنفذة **77 = 71 ناجحة + 6 فاشلة، وصفر تخطي/أخطاء جمع**. فحوص audits نفسها بـRuff وformat ناجحة أيضًا.

| الملاحظة | المطلوب مقابل السلوك الفعلي المعاد إنتاجه | دليل الكود والاختبار | أثر الحالة |
| --- | --- | --- | --- |
| A01 | الدعم يجب أن يعكس المصدر؛ Replay يبقي MAF=UNSUPPORTED في العينة ثم يعلنه مدعومًا في get_capabilities | sources/replay.py:51؛ test_fr002_replay_must_not_advertise_explicitly_unsupported_sensor | FR-002 → Partial |
| A02 | نسخة العقد يجب أن تكون integer 1؛ sample_version=true في ملف Replay مقبولة لأن True == 1 | core/models.py:109؛ test_fr004_data001_replay_rejects_boolean_contract_version | FR-004 وDATA-001 → Partial |
| A03 | نهاية الحدث النهائي لا تسبق الكشف وآخر عينة؛ Event.from_dict يقبل COMPLETE/end_ms=0 مع trigger/sample=1000 | core/models.py:167–182؛ test_data001_finalized_event_rejects_end_before_trigger_and_last_sample | DATA-001 → Partial |
| A04 | تغيير boot/session يحفظ العينات المقبولة المعلقة قبل بدء الجديدة؛ HELLO جديد يستدعي samples.clear فيضيع sample قديم بلا خطأ | protocol/receiver.py:100–103؛ test_fr012_boot_transition_preserves_already_accepted_pending_samples | FR-012 → Partial |
| A05 | عينة حية ثم رفع حدث يحمل العينة المنطقية نفسها يجب أن يندمجا؛ معلومات host receipt/raw/device تختلف، فتقارن SQLite كل JSON وترفض الرفع | core/session.py:44–52، storage/sqlite_repository.py:99–105؛ test_fr012_live_samples_then_matching_event_upload_are_importable | FR-012 → Partial؛ المعاملة تمنع الكتابة المتعارضة لكنها لا تحقق تكامل الرفع |
| A06 | فشل ملف التصدير لا يدل على فقد المصدر؛ except العام يولد CONNECTION ويوقف Simulation سليمة عند FileNotFoundError | ui/worker.py:99–130؛ test_fr006_nfr001_export_file_error_is_not_a_connection_loss | FR-006 وNFR-001 → Partial |
| A07 | استقبال Firmware لا يطبق الحقول الإلزامية كلها؛ minimal HELLO يمر بالمسار الثابت لـC ويرفضه Python | firmware/main/device_protocol.c:104–118؛ firmware-review.json؛ static review فقط | FR-013 يبقى Partial، ويمنع ادعاء FR-012 مطابقة تشغيلية كاملة |

هذه المراجعة لم تصلح أيًّا من A01..A07 ولم تضف ميزات؛ تركت الاختبارات الفاشلة ظاهرة لإعادة التحقق بعد تكليف إصلاح مستقل. نجاح المسار الأساسي لا يلغي فقد البيانات والتصنيف الخاطئ في الحالات المعاد إنتاجها.

### سجل التنفيذ الأول — تاريخي، وليس قرار القبول الحالي

بوابات نُفذت بالتتابع: foundation (16 ناجحًا) → recording (8) → pipeline/reports (5 أوليًا) → GUI (2) → protocol/device path (25 أوليًا) → E2E-01..08 (8)، ثم أضيفت اختبارات العمر وفشل الموارد والمصافحة/ACK/ERROR وسلامة ترتيب أحداث النقل، وأعيدت بوابة التحقق الشاملة.

الأوامر الفعلية من الجذر:

```powershell
.\.venv\Scripts\python.exe -m pytest desktop/tests -q --junitxml=docs/evidence/pytest.xml
.\.venv\Scripts\python.exe -m ruff check desktop scripts
.\.venv\Scripts\python.exe -m ruff format --check desktop scripts
.\.venv\Scripts\python.exe -m mypy --config-file desktop/pyproject.toml desktop/src/doctorcar
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -X utf8 scripts/run_e2e.py
.\.venv\Scripts\python.exe -X utf8 scripts/preview_ui.py
```

| الفحص | النتيجة | الدليل |
| --- | --- | --- |
| pytest | 71 ناجحًا، 0 فشل، 0 أخطاء، 0 تخطي؛ منها 52 وحدة و11 تكامل و8 E2E | [pytest.xml](evidence/pytest.xml)، [pytest.log](evidence/pytest.log) |
| Ruff + format | ناجحان على 39 ملف Python؛ build وtmp مستبعدان | [quality.log](evidence/quality.log) |
| mypy strict | ناجح على 30 ملف source | quality.log |
| pip check | بلا اعتماديات مكسورة | quality.log وpackage-validation.log |
| E2E مستقل | normal بلا حدث؛ thermal/invalid/dropout/device_protocol حدث واحد مكتمل لكل سيناريو؛ 156 عينة لكل مصدر؛ reload صحيح | [e2e-run.json](evidence/e2e-run.json) والتقارير report-*.txt |
| GUI lifecycle | اختبار المصدر والتنقل وduplicate start وإغلاق/إعادة فتح التقرير، وفشل SQLite دون إسقاط GUI | E2E-08 وintegration/test_ui |
| فحص بصري native Windows | العربية والـRTL والقيم السالبة والوحدات والمعرفات ظاهرة؛ أربع صور فُحصت | [dashboard](evidence/ui-dashboard.png)، [sensors](evidence/ui-sensors.png)، [events](evidence/ui-events.png)، [report](evidence/ui-report.png) |
| Wheel + بيئة جديدة | بناء وتثبيت في .verification-env، استيراد -I من site-packages، مخطط مضمّن، CLI وnative Qt init/run/close | [package-validation.log](evidence/package-validation.log) |
| Firmware/مركبة/منفذ فعلي | لم تُشغل؛ لا SDK في PATH ولا عتاد مُختبر | [environment.json](evidence/environment.json) |

اختبارات الوحدة تغطي متطلبات الحالات الـ18: النماذج، الأنواع والوحدات، الدعم والغياب والعمر، التسلسل، النافذة، قبل/بعد، التداخل والتكرار، إعادة الفتح، التقرير ونقص الأدلة، الترميز والإصدارات والتلف. التكامل يغطي خطوط المصادر→التسجيل→SQLite→التقرير، protocol→shared stream، restart وfake disconnect/reconnect. التخطي صفر لا يعني وجود اختبارات عتاد ناجحة؛ اختبار العتاد غير منفذ أصلًا.
فشلت أثناء التطوير محاولة اختبار سبقت نهاية تثبيت الحزمة، وتوقع عدد أطوار غير صحيح في اختبار المحاكاة، ومقارنة tuple/list بعد JSON في التخزين، وموضع كتلة داخل اختبار جديد وبعض قواعد التنسيق؛ صُححت آنذاك وأعيدت الاختبارات ذات الصلة. ادعاء عدم وجود إخفاق معروف في التقرير الأول لم يعد صالحًا: المراجعة الحالية في بداية M تكشف ستة إخفاقات قبول وملاحظة ثابتة في Firmware.
فحص offscreen السلوكي لا يحمّل الخطوط على هذه البيئة كما يفعل native Windows؛ ظهر tofu في المعاينة الأولى، وأعيد التصوير بمحرك Windows مع WA_DontShowOnScreen. لم يعتمد نجاح الرسم العربي على offscreen، ولم يُنفذ اختبار بشري مطول لكل قياس شاشة/دقة DPI.
بيئة الفحص: Windows 11 build 26200، Python 3.14.6، Git 2.54.0.windows.1؛ PySide6 6.12.0 وpyserial 3.5 وjsonschema 4.26.0 وpytest 9.2.0 وRuff 0.17.3 وmypy 1.20.2. التفاصيل والتراخيص المعلنة من metadata في [dependencies.json](evidence/dependencies.json)، والإصدارات مثبتة في desktop/requirements-lock.txt. حزم global لم تستخدم في بيئتي المشروع.

## N. Risk Register

| الخطر | المعالجة | التحقق |
| --- | --- | --- |
| تشخيص قطعي زائف | أدلة وحدود ومقارنة وسياق تجريبي | اختبارات التقارير |
| زمن خاطئ أو نوافذ مضطربة | زمن نسبي/مصدر/جلسة/تسلسل والتحقق منها | unit + E2E |
| فقد بيانات/طاقة | transactions وcheckpoint وpartial واسترجاع | storage recovery tests |
| تجميد GUI أو ازدواج الجلسات | worker واحد وعقد Session واحد | UI lifecycle tests |
| رسائل تالفة أو كبيرة | حدود framing وschema وتسلسل وhash | protocol tests |
| إعادة استيراد نفس الحدث | هوية ثابتة وقيود DB | replay/import tests |
| عدم توفر SDK/عتاد | توثيق Unverified بلا ادعاء | tool inspection |
| ترخيص التوزيع | مراجعة PySide6 ومكونات Qt قبل النشر، لا توزيع حالي | سجل قرار |
| A07 مفتوح؛ A01..A06 مصححة | لا اعتماد عتادي قبل إصلاح تحقق C والبناء واللوحة | dc-cr-002/final.xml؛ Firmware محفوظ دون تعديل |

## O. Decision Log

- D01: PySide6 وفق التكليف؛ QThread/queued signals لفصل العمل عن GUI، وSQLite في worker. مرجع: https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html
- D02: pyserial بمهلة محدودة دون فتح تلقائي أو إرسال للمركبة. مرجع: https://pyserial.readthedocs.io/en/latest/pyserial_api.html
- D03: لا NumPy/Pandas/ML/SHAP في M1؛ عقود فقط. لا خدمة ويب أو Cloud.
- D04: `.venv` في الجذر وحزمة src-layout تحت desktop؛ اختبارات pytest وأدوات Ruff/mypy. https://docs.pytest.org/en/stable/how-to/usage.html وhttps://docs.astral.sh/ruff/configuration/
- D05: تراخيص Qt/PySide6 تتطلب مراجعة التوزيع ومكونات Qt المستخدمة؛ هذا تشغيل تطوير محلي لا قرار ترخيص توزيع. https://doc.qt.io/qtforpython-6/licenses.html . python-OBD غير مثبت كاعتماد للمشروع وغير منفذ، وتؤجل مراجعة ترخيصه لاختيار M5.
- D06: native USB Serial/JTAG لبيانات Firmware وUART للـconsole؛ استهداف ESP-IDF 5.5.x، وإثبات البناء مشروط بتوفره. الوثائق: https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/ . تعذر جلب بعض صفحات Espressif عبر أداة الويب أوليًا، ثم راجعت المصدر الرسمي كما في D08 قبل كتابة API.
- D07: jsonschema اعتماد تشغيل مبرر بالتحقق من مخطط واحد لجميع رسائل النقل؛ schema مضمن في الحزمة ومدخل الجذر $ref محلي، لا نسختان مستقلتان. ترخيص metadata مسجل، ولا حاجة لمكتبات ML في M1.
- D08: راجعت مصدر Espressif الرسمي v5.5.1 بدل الصفحات المتعذرة: [USB driver header](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/esp_driver_usb_serial_jtag/include/driver/usb_serial_jtag.h)، [component dependencies](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/esp_driver_usb_serial_jtag/CMakeLists.txt)، [timer](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/esp_timer/include/esp_timer.h)، [MAC](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/esp_hw_support/include/esp_mac.h)، [random](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/esp_hw_support/include/esp_random.h)، [json component](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/json/CMakeLists.txt)، [console Kconfig](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.1/components/esp_system/Kconfig). هذه مراجعة API وليست بناءً أو اختبار عتاد.
- D09: حفظ checkpoints لكل عينة حدث، مع تخزين العينات الجديدة فقط والتحقق من تعارض القديم عند الإنهاء، لتقليل إعادة التسلسل مع بقاء الاستعادة قابلة للاختبار. لا ضمان زمني بلا قياس؛ سرعة العرض المطلوبة قد تنخفض مع الحمل.
- D10: المخطط يولد تشخيصًا سياقيًا محدودًا لا حكمًا على قطعة؛ قيم المحاكاة حرارية مبسطة وعتبات demo معلنة، وDTC/Freeze Frame لا يُخترعان لإكمال التقرير.
- D11: لم يُنشأ مستودع Git بعيد، ولم تُرسل ملفات المشروع إلى خدمة خارجية. جُلبت حزم ووثائق رسمية فقط، وأُنشئت جميع ملفات التطبيق من الصفر. Git المحلي متاح ولم تُنشأ commits تلقائية.
- D12: Acceptance Audit مستقل أعاد تشغيل الأدلة ووسع حالات الاختبار دون تعديل المنتج. الحكم PARTIAL، والحالات الأحدث في C تتقدم على استنتاج التنفيذ الأول. لا إصلاحات تطبيقية ولا M2 ضمن هذه المراجعة.

قرارات DC-CR-002:
- D13: EventSink حد حفظ للمسجل نفسه؛ توليد تاريخ في ذاكرة برمجية محدودة لا ينشئ Recorder/Session manager/SQLite ثانية.
- D14: تغيير HELLO يفرغ التجميع غير المكتمل ويحتفظ بالعينات المقبولة المعلقة؛ لكل جلسة validator/detector/recorder مستقل داخل Session الموجودة.
- D15: تكافؤ القياس يستثني raw/received_at_ms/device_id فقط؛ يحتفظ بأول استقبال ويرفض تعارض قيمة أو جودة أو مصدر أو provenance.
- D16: Ground Truth في simulation_runs ومقارنة اختبار لاحقة بالقاعدة والزمن، لا يدخل الاستدلال. MAF/MAP/voltage/trim/أنماط الاشتباه بلا قاعدة توصف للعرض فقط.
- D17: QSettings في ملف INI بجوار DB يحفظ اللغة والمظهر وSeed؛ التقارير الإنجليزية تحافظ على النص التشخيصي العربي الأصلي، دون إعادة كتابة التاريخ. تغيير اللغة لا يجدد عمر آخر قراءة.
- D18: فحص المصدر داخل DataSource، ولا Connectivity Service؛ USB يفتح مرة ويغلق حتمًا، والمصادر تقفل أثناء التشغيل. A07 ممنوع تعديله في CR؛ M1 يبقى PARTIAL.

## P. Project Backlog

بعد DC-CR-002 أُغلقت A01..A06 بدليل اختبارات القبول القديمة نفسها. قبل اعتماد M1 كاملًا يبقى A07 والتحقق من بناء Firmware ومخرجاته عند توفر SDK واللوحة؛ لا تعديل Firmware مأذون هنا.
M2: تجهيز datasets حسب الرحلات/السيناريوهات، pandas/NumPy/scikit-learn، خصائص زمنية، Isolation Forest كنقطة بداية، baseline عادل، Precision/Recall/false alarms/delay، منع تسرب النوافذ.
M3: XAI مناسب للنموذج مثل SHAP، خلفية من التدريب، حدود التفسير.
M4: كتالوج ميكانيكي معتمد بمراجع واختبارات لكل عامل/فرضية؛ لا ادعاء تغطية 80/68.
M5: TWAI محمي وISO-TP/OBD للقراءة فقط، MicroSD وتسجيل محلي وفقد طاقة ومزامنة وسكون، الجهد بواجهة مستقلة، اتصالات إضافية عند الحاجة.
M6: تحقق bench للهاردوير والطاقة والتوافق، ثم اختبار مركبة بموافقة منفصلة.
M7: تقييم الدقة والقيمة الإضافية والموثوقية والتراخيص وتسليم موثق.

## Q. Milestones & Acceptance Gates

| المرحلة | النطاق والمخرجات | التبعيات/الخطر | بوابة القبول والدليل |
| --- | --- | --- | --- |
| M0 | baseline ومعمارية ومخاطر وعقود | المتطلبات الحالية؛ التفاصيل البحثية ناقصة | ملف التحكم وأسماء IDs ومسار بيانات واحد |
| M1 | التطبيق والمحاكاة وReplay والأحداث والتقرير والبروتوكول وFirmware TEST | M0، حزم Python؛ SDK/عتاد قد يغيب | pytest/Ruff/mypy/install/E2E ودليل GUI، بناء firmware إن توفر وإلا قيد صريح |
| M2 | multivariate time-series ML | M1 وبيانات وتسمية موثوقة | تقييم مستقل مقابل baseline دون تسرب |
| M3 | تفسير النموذج | M2 ونموذج متحقق | تطابق التفسير مع الخرج وحدود السببية |
| M4 | معرفة ميكانيكية موسعة | مصادر وكتالوج معتمد | اختبار كل فرضية وقيود تغطية |
| M5 | CAN وMicroSD firmware | تصميم حماية وbench وSDK | اختبارات نقل وتخزين وفقد طاقة وقراءة آمنة |
| M6 | تكامل عتاد فعلي | M5 وهاردوير متاح وموافقة | bench ثم مركبة ضمن النطاق المأذون |
| M7 | تقييم وتسليم | أدلة المراحل السابقة | مراجعة نتائج وحدود وتراخيص وتسليم قابل للإعادة |

كل مرحلة تشمل متطلباتها في baseline أو تفصيل لاحق قبل بدء التنفيذ؛ بوابة M1 لا تمنح إذن بدء M2.

## R. Known Limitations

العيب المفتوح الحالي A07: تحقق غلاف C ناقص. A01..A06 مصححة واختباراتها الستة الأصلية ناجحة دون تعديلها. لا ادعاء تحقق الجهاز؛ Firmware محفوظ دون تغيير وبناؤه وتشغيله غير منفذين.
لا سيارة فعلية ولا ECU Freeze Frame ولا كتالوج 68 حالة (ML وXAI منفذان في محاكاة؛ انظر DC-CR-005) ولا CAN/MicroSD/قياس جهد فعلي. المحاكاة نموذج تشغيل مبسط لا نموذج فيزيائي معتمد. بناء Firmware ومخرجاته والاتصال الفيزيائي غير متحققين. لا resume آلي للأجزاء ولا إعادة فتح منفذ تلقائية؛ تعاد المصافحة والرفع كاملًا بطلب المستخدم. التطبيق لا يرسل ACK أو HELLO عبر Serial، بل ينتظر الإعلان الدوري.
ملف SQLite يستخدمه recorder واحد في التطبيق؛ فتح تطبيقين على الملف نفسه أثناء التسجيل غير مدعوم. الاستعادة بعد انقطاع العملية تستعيد آخر معاملة مكتملة، ولا تضمن آخر عينات لم تصل أو لم تُكتب قبل انقطاع الطاقة. البيانات التجريبية لا تثبت دقة تشخيص على أسطول سيارات. لا تقييم ML أو مقارنة قيمة إضافية مدّعاة قبل M2.
الاختبار البصري آلي مع مراجعة الصور لمحرك Windows؛ تنوع DPI والقارئ الصوتي والتجارب الميدانية تحتاج تحققًا لاحقًا. لا ضمان معدل حقيقي لـ30× تحت كل حمل. نطاقات الصلاحية العامة في السجل None دون مواصفة موثوقة؛ حدود validator معلنة للمحاكاة فقط.

## S00. DC-UX-001 — إعادة تصميم تجربة المستخدم (الأحدث)

**M1 = PARTIAL.** `316 passed / 0 failed / 0 skipped` (153 ث؛ 280 سابقة + 36 جديدة في `desktop/tests/cr007`). تغيير عرض فقط: Session/EventRecorder/Repository/القواعد/ML/XAI/السياسة الاستشارية/النموذج v3/Firmware لم تتغير، وبصمة `data/doctorcar.sqlite3` لم تتغير بفعل هذه المهمة (انظر FINAL_UX_ACCEPTANCE). إضافة وحيدة على العامل: إشارة `session_stats`.

| المعرف | المتطلب | الحالة | الدليل |
| --- | --- | --- | --- |
| UX-101 | نظام تصميم موحد (tokens، سلم نوع، QSS واحد، تباين AA، خطوط نظام) | Completed | `ui/theme.py`، `test_palette_text_contrast_meets_wcag_aa` |
| UX-102 | شاشة بدء بمراحل فعلية، مهلة، فشل ودّي، نافذة واحدة؛ من المصدر ومن Wheel | Completed | `test_startup.py` (9)، `screenshots/splash/*.json`؛ فشل ML native NOT TESTED |
| UX-103 | نافذة رئيسية: ترويسة، تنقل بأيقونات وطي، تذييل، إشعارات | Completed | `test_ux_views.py`، 144 تركيبة تخطيط |
| UX-104 | لوحة تحكم بـ8 حالات اتصال حقيقية وإجراءات سريعة | Completed | اختبارات الحالات + لقطات |
| UX-105 | حساسات: بطاقات، جودة بنص ورمز، Missing≠0، قديمة بلا حركة، بحث/تصفية | Completed | اختبارات + QA-EXT-004 |
| UX-106 | أحداث وتقارير: بحث/تصفية/ترتيب/تحميل تدريجي/خط زمني/نسخ | Partial | الأقسام القابلة للتوسيع: التفاصيل الفنية فقط؛ لا مستوى خطورة معتمد؛ محتوى التقرير لم يتغير |
| UX-107 | اتصال ومحاكاة: خطوات، وصف سيناريو، تقدم محدد فقط، ملخص | Completed | `pr_gui*`، `pr_gui_ext` |
| UX-108 | إعدادات: لغة، ثيم، حجم، تقليل حركة، تفضيلات، عن؛ حفظ فوري | Completed | اختبارات الحفظ |
| UX-109 | حركة وإشعارات تحترم إعداد Windows؛ دمج التكرار؛ الخطأ دائم | Completed (اختبار برمجي) | الحركة لم تُشاهد: تأثيرات Windows معطلة على الجهاز |
| UX-110 | إمكانية وصول واستجابة (تركيز، أسماء، تحجيم) | Partial | 0 قص/تجاوز؛ تحجيم Windows الفعلي وقارئ الشاشة NOT TESTED |

الأدلة: `docs/evidence/ui-ux-redesign/` (`UI_AUDIT.md`, `DESIGN_SYSTEM.md`, `UX_CHANGELOG.md`, `GUI_TEST_RESULTS.md`, `SCREENSHOT_INDEX.md`, `FINAL_UX_ACCEPTANCE.md`). اختبار cr002 عُدّل سطرين (ألوان hex ← tokens) موثق. قرار D-UX-1: ML يبقى استشاريًا ويُعرض بصيغة «AI (استشاري)» ولا يُسمّى تشخيصًا.

## S0. DC-FIX-001 — معالجة عيوب DC-QA-001

**M1 = PARTIAL.** `280 passed / 0 failed / 0 skipped` (124 ث؛ 193 سابقة + 87 في `desktop/tests/cr006`). العيوب: 11 مغلقة (DEF-001 بحدود وDEF-004 بحدود)، 2 جزئية (DEF-002، DEF-003)، 1 مفتوح (DEF-008 Firmware A07: Patch مقترح غير مبني). تغييرات مرتبطة بالمتطلبات: DATA/SAF — حدود صلاحية مستقلة عن المصدر وإسقاط الحساس المجهول (`monitoring/data_quality.py`)؛ FR-005 — إنهاء الأحداث المنتهية قبل تقييم المحفزات عند T+30 (`monitoring/event_recorder.py`)؛ MS-RULE — اكتشاف تجميد MAP وعدم إخفاء MS_AIRFLOW (`monitoring/evidence_rules.py`)؛ SIM-003 — تكرار دورة القيادة للجلسات >155 ث؛ AI-008/009 — سياسة ML استشارية (`Session.ml_alerts`) والنموذج الافتراضي `cr006-iforest-v3` بعد مقارنة مستقلة (قواعد/ML/دمج)؛ UX — أخطاء مفهومة، DTC يتبع اللغة، لا تكرار فحوص. القرار D-FIX-1: v3 افتراضي لأنه الأقل إنذارات كاذبة (0 مقابل 7 لـv2 على Test مستقل 76 رحلة) رغم أن ML لا يضيف كشفًا. الأدلة: `docs/evidence/remediation/` (`FINAL_ACCEPTANCE_REPORT.md`, `FIX_VERIFICATION_MATRIX.md`, `ML_BEFORE_AFTER.md`, `REMAINING_RISKS.md`). Firmware لم يتغير؛ بناؤه وتشغيله NOT TESTED.

## S. Final Readiness Assessment

**DC-CR-003 = PASS وظيفيًا في النطاق المختبر؛ M1 = PARTIAL.**138 اختبارات ناجحة، صفر فشل/أخطاء/تخطي؛107 القديمة نفسها و31 جديدة. قواعد S01..S07 تعمل من علاقات القراءات دون معرفة اسم الحقن، وتوفر فرضيات وفحوصًا وقياسات فعلية وتصنيفًا مستقلًا عن Quality. Replay/التاريخ/USB الوهمي/الإعدادات والتسجيلT±30 متوافقة، و22 بصمة اختبار/Firmware لم تتغير.

تجربة Qt الفعلية نجحت مع حفظ واسترجاع تقرير AR/EN مطابق: كشف66s، نافذة36..96s/301 عينة وSQL سليم. راجعت صور اختيار السيناريوهات وعلامة التحديد والسجل الموسع والتقرير الداكن الإنجليزي؛ الواجهة الحالية محفوظة مع ضبط عناصر الحقن والتمرير. Ruff/format/mypy/pip check ناجحة. لا ادعاء تحقق DPI/قارئ شاشة/لوحة/USB فعلي أو ESP-IDF.

التقييم16/21 تطابق نمط فقط؛5 حالات غير مكتشفة باقية، صفر إنذارات في3 رحلات طبيعية، ولا ثقة سببية أو تعميم على سيارات. A07 وقيود العتاد باقية. لا قياسات جديدة مخترعة، ولا DTC/FreezeFrame/Fuel Pressure مزيفة، ولا ML/XAI أو M2/M3. الأدلة الحالية في evidence/dc-cr-003. حالات MS الخمس Completed تعني استيفاء الوظيفة والاختبار وحدودها الموثقة، لا كشفًا شاملًا.

### سجل الاستعداد السابق CR002 — تاريخي

**DC-CR-002: PASS للنطاق البرمجي المختبر. M1: PARTIAL.** المصفوفة الحالية 15 Completed / 4 Partial / 1 Deferred. 107 اختبارات ناجحة، صفر فشل/أخطاء/تخطي؛ 71 أصلية + 6 قبول سابق + 30 جديدة. A01..A06 Fixed مع اختبارات القبول المحمية، A07 Open خارج النطاق.

تجربة native Qt جديدة نجحت: حقن 60..65s، كشف 63s، نافذة33..93s/301 عينة، حفظ/تصدير/Replay، استيراد حدثين تاريخيين كاملين وإعادة الاتصال دون تكرار، تطابق جميع القراءات والجدول عند10×/30×، Legacy89s، وحفظ EN/Dark/LTR وتقرير مطابق بعد إعادة فتح DB. SQL integrity=ok وforeign_key_check فارغ. راجعت صور Light/AR وDark/EN؛ المعرفات تعرض باتجاه تقني دون تغيير قيمها.

Ruff/format/mypy/pip check ناجحة وفق quality.log. بصمات 17 ملفًا محميًا تطابقت في protected-after.json: اختبارات M1 الأصلية والقبول السابق وFirmware دون تعديل. لم يُفتح منفذ فعلي ولم يُفلش جهاز. لا build ESP-IDF ولا USB/لوحة/مركبة؛ لا CAN/MicroSD حقيقي ولا AI/M2/M3. System theme غير منفذ، وليس ضمن إلزام Light/Dark. تنوع DPI وقارئ الشاشة والبيئة العتادية غير مختبر.

الأدلة الحالية في evidence/dc-cr-002، والأدلة السابقة في acceptance-audit سجل تاريخي محفوظ. تجربة CR الأولى توقفت بمهلة انتظار Replay الحقيقي قبل تعديل برنامج التجربة لفحص الملف وتشغيله وإيقافه؛ e2e-attempt1.log محفوظ، والمحاولة النهائية e2e.log/json ناجحة. لم تُعدّل الاختبارات القديمة لتغيير نتيجة فشل.

DC-CR-004 Gate1 PASS: 15 passed في22.63s؛ gate1.log/xml. فشل ترجمة زر جديد أصلح في التطبيق، لم تعدل الاختبارات. UX-001/002/003 منفذة واختبرت، الربط بـAI لم ينفذ بعد.

DC-CR-004 Gate2 PASS fonctionnel: 30 passed في1.81s. Dataset2: train12/validation16/test16 (heldout4000..4015). التقييم الأول seeds3000 استكشافي متقاعد بعد اكتشاف ضعف العتبة. الاختيار النهائي12 من47 ميزة حسب العلاقات والحرارة/الجهد/التصحيح، معايرة F1 علىvalidation فقط. لا ادعاء استقلال عن المولد. Model iforest-cr004-v1 محفوظ؛ test ML precision0.392045 recall0.436709 مقابلrules0.898955/0.816456. النتائج والبيانات فيdata/cr004-dataset وevidence/dc-cr-004.

DC-CR-004 Gate3 PASS: 21 passed في4.80s. Session analyzer اختياري خارج GUI، تفعيل صريح في الواجهة،3 نوافذ متتالية وhysteresis0.02،دمجRule/ML ضمن10s مع بقاء أحداث الجودة مستقلة.776/776 عينة وT±30. DB corev2 محفوظ لاختبارات التوافق،extension_migrations analysis-reports=1 توسعة إضافية لجداولanalyses/event_analyses/diagnostic_reports دون تحويل العينات القديمة.

DC-CR-004 Gate4 PASS: 4 passed في4.00s. grouped-training-median-perturbation-v1 تفسيرscore النموذج نفسه،اختباركلreplacement/effect عدديًا،hash/window/reference وتغيرالمدخلات ورفضmodelمختلف. لا SHAP ولاجمعمساهمات/سببميكانيكي. الحساب فيBackendWorker.

DC-CR-004 Gate5 PASS software: 32 passed في16.19s. TCP localhost فقط،عمليتان،HELLO/CAPS/heartbeat/sample/event protocol1،history61samples لكلحدث محفوظقبلالاتصال،idempotent بعدreconnect،bootجديدمع51+51 عينةمعزولة،رسائلغيرصالحةمرفوضة. no client commands. Firmware غيرمعدل/غيرمبني: idf.py/CMake/Ninja غائبة عنPATH؛لاWiFiFirmware أوCAN/MicroSDمدعى.

DC-CR-004 Gate6 PASS: 16 passed في26.50s. تقريرAR/ENمبسطافتراضي،technicalbuttonورسم11حساسًا،تحليلAI/XAIمحفوظيستعادبدونتدريب،الإصداروقيمةالكشفمنالنافذةالأصلية. فحوصالتوافقمعالتقاريرالقديمةوالإعداداتناجحة. يجبتوثيقالتحليلاللاحقلكشفالقاعدةبوقتهالخاص.
