# DoctorCAR — Defect Register (DC-QA-001)

لم يُصلَح أي عيب خلال الحملة. الحالة OPEN لكل العيوب. الخطورة: CRITICAL فقد بيانات/فساد/سلامة؛ HIGH خلل رئيسي في التشخيص أو AI أو التكامل؛ MEDIUM وظيفة جزئية أو سلوك غير صحيح مع بديل؛ LOW عيب بصري أو تحسين محدود.

## DEF-001 — ML يضيف إنذارات كاذبة دون زيادة في الكشف؛ دقة الدمج (قواعد+ML) أقل من القواعد وحدها

- **الخطورة:** HIGH
- **الفئة:** عيب AI
- **المتطلب المتأثر:** AI-008 / AI-009 / INT-002
- **خطوات إعادة الإنتاج:** شغّل `python audits/qa/qa_ml_eval.py` (52 رحلة مستقلة بذور 9000+) أو شغّل رحلات طبيعية في الواجهة بتفعيل AI.
- **المتوقع:** تفعيل ML لا يخفض الدقة، ويضيف كشفًا (أبكر أو أوسع) أو يبقى استشاريًا فقط.
- **الفعلي:** قواعد فقط: 27/28 أحداث و0 إنذار كاذب (دقة 1.00). ML v2: 5/28 و4 إنذارات كاذبة (1.79/ساعة). الدمج: 27/28 و4 كاذبة (دقة 0.897). ML v1: 13/28 و97 كاذبة (43/ساعة). كل ما اكتشفه ML اكتشفته القواعد أيضًا.
- **الدليل:** docs/evidence/full-qa/gate5/ml-eval.json؛ ml-eval-alarms.csv؛ QA-AI-010
- **السبب الجذري (مثبت/مشتبه):** IsolationForest يعزل أطراف توزيع الأطوار الطبيعية؛ القواعد مبنية على المولد نفسه فتبدو مثالية؛ معايرة العتبة تبادلت الاستدعاء بالإنذارات.
- **الأثر على DoctorCAR:** أحداث ML المعروضة للمستخدم أغلبها كاذب أو مكرر للقواعد؛ يضعف الثقة بميزة AI.
- **الملفات المتأثرة:** analysis/analyzer.py؛ core/session.py (دمج حدث ML)؛ analysis/models/*
- **الإصلاح المقترح:** اجعل ML استشاريًا (لا يُنشئ حدثًا) أو اشترط تأييد قاعدة؛ أعد تقييم نموذج سياقي/معايرة على بيانات جديدة؛ أبلغ عن ML بشكل منفصل في التقرير.
- **اختبار Regression المطلوب:** qa_ml_eval.py على 52 رحلة جديدة: إنذارات الدمج الكاذبة <= القواعد وحدها وrecall الدمج >= القواعد
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع عرض المسار الكامل؛ يمنع ادعاء قيمة مضافة لـAI ما لم يُعلن ML استشاريًا
- **الحالة:** OPEN

## DEF-002 — إنذارات ML الكاذبة ما زالت قائمة في رحلات الإحماء مع معامل قيادة مرتفع (1.08–1.15)

- **الخطورة:** HIGH
- **الفئة:** عيب AI
- **المتطلب المتأثر:** AI-009
- **خطوات إعادة الإنتاج:** شغّل `qa_ml_eval.py` (مجموعة stress: 12 رحلة باردة) أو `AnomalyAnalyzer` على رحلة باردة بمعامل 1.14.
- **المتوقع:** لا إنذار ML في قيادة طبيعية.
- **الفعلي:** v2: 5 أحداث كاذبة في 5/12 رحلة (عند ~63–64 ث انتقال التسارع إلى السير)؛ v1: 32 إنذارًا في 12/12 رحلة. الحالة QA-AI-011 FAIL.
- **الدليل:** docs/evidence/full-qa/gate5/ml-eval.json (stress_cold_high_scale)
- **السبب الجذري (مثبت/مشتبه):** تغطية تدريبية/عتبة غير كافية لطرف توزيع معامل القيادة؛ لا ميزة سياق تشغيل.
- **الأثر على DoctorCAR:** إنذار ML كاذب في ~40% من رحلات الإحماء المرتفعة؛ الواجهة لا تعرض معامل القيادة فلا يمكن إعادة إنتاجه يدويًا.
- **الملفات المتأثرة:** analysis/benchmark.py؛ analysis/windows.py؛ analysis/models/*
- **الإصلاح المقترح:** أضف مدى معامل القيادة كاملًا وبدايات متنوعة للتدريب، ونموذجًا سياقيًا للإحماء، وقيّم على Test جديد؛ لا تغيّر الافتراضي دون مقارنة موثقة.
- **اختبار Regression المطلوب:** مجموعة stress (12 رحلة باردة بمعامل 1.08-1.15): صفر إنذار ML، مع اختبار pytest للمعاملات القصوى
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع العرض بقواعد فقط؛ يلزم إصلاحه أو الإفصاح قبل عرض AI أمام لجنة
- **الحالة:** OPEN

## DEF-003 — فجوات في اكتشاف القواعد حسب الظرف والمدة

- **الخطورة:** MEDIUM
- **الفئة:** عيب تطبيق (محرك القواعد)
- **المتطلب المتأثر:** MS-RULE / MS-SIM
- **خطوات إعادة الإنتاج:** شغّل `python audits/qa/qa_events_db.py` (QA-EVENT-015).
- **المتوقع:** كل عطل محقون إما يُنتج حدثًا أو تُوثَّق فجوته.
- **الفعلي:** 25/35 تركيبة أنتجت حدثًا؛ لم تُكتشف: S01 وS02 وS03 وS04 بمدة 5 ث؛ وS02 وS03 وS04 عند البدء 110 ث (تباطؤ/خمول) و135 ث. كذلك flatline لـS07 (3/4 أحداث S07 في المجموعة المستقلة).
- **الدليل:** docs/evidence/full-qa/gate4/detection-coverage.json؛ gate5/ml-eval.json
- **السبب الجذري (مثبت/مشتبه):** شروط القواعد تتطلب محركًا يعمل بحمل/خانق ومدة كافية ومراجع صالحة.
- **الأثر على DoctorCAR:** أعطال هواء/وقود في أطوار التباطؤ والخمول وقصيرة المدة لا تُسجَّل؛ الموثق في ملف التحكم 5 حالات فقط.
- **الملفات المتأثرة:** monitoring/evidence_rules.py؛ monitoring/event_detector.py
- **الإصلاح المقترح:** وثّق الفجوات في README/ملف التحكم؛ أضف قواعد/نوافذ تناسب الخمول والتباطؤ؛ أضف حدث «مرجع غير كافٍ» حين تُعطَّل القاعدة.
- **اختبار Regression المطلوب:** مصفوفة QA-EVENT-015 (35 تركيبة): كل تركيبة تُنتج حدثًا أو حدث «تعذر التقييم»
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع؛ يجب الإفصاح عن الفجوات
- **الحالة:** OPEN

## DEF-004 — العطلان المتزامنان قد يخفي أحدهما الآخر: S04 لا يُكتشف عند وجود S07 flatline

- **الخطورة:** MEDIUM
- **الفئة:** عيب تطبيق (محرك القواعد)
- **المتطلب المتأثر:** MS-RULE / INT-002
- **خطوات إعادة الإنتاج:** شغّل `python audits/qa/qa_masking.py` (QA-SIM-038).
- **المتوقع:** S04 يبقى مكتشفًا عند وجود عطل ثانٍ.
- **الفعلي:** S04 وحده: MS_AIRFLOW عند 66.2 ث. S04 + S07 flatline: لا أي حدث ولا تفسير.
- **الدليل:** docs/evidence/full-qa/gate10b/masking.json
- **السبب الجذري (مثبت/مشتبه):** قاعدة S04 تتطلب مرجع MAP صالحًا؛ تجميد ضغط السحب يُبطله فتُعطَّل القاعدة بصمت.
- **الأثر على DoctorCAR:** يخفي عطلًا حقيقيًا عندما يتزامن مع عطل إشارة؛ يضلل المستخدم بغياب الإنذار.
- **الملفات المتأثرة:** monitoring/evidence_rules.py
- **الإصلاح المقترح:** عند تعطيل قاعدة بسبب مرجع غير صالح أصدر حدث «لا يمكن التقييم» مع السبب؛ اختبر مصفوفة التركيبات.
- **اختبار Regression المطلوب:** QA-SIM-038: S04 يبقى مكتشفًا مع S07 flatline أو يصدر حدث «تعذر التقييم»
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع العرض بأعطال منفردة؛ يمنع ادعاء كشف الأعطال المتزامنة
- **الحالة:** OPEN

## DEF-005 — عطل ثانٍ من النوع نفسه يبدأ عند حد T+30 بالضبط يُبتلع (لا حدث مستقل)

- **الخطورة:** MEDIUM
- **الفئة:** عيب تطبيق (مسجل الأحداث)
- **المتطلب المتأثر:** FR-005
- **خطوات إعادة الإنتاج:** شغّل `python audits/qa/qa_masking.py` (QA-EVENT-016): S07 dropout عند 90 ث ثم عند 120.0 ث.
- **المتوقع:** كل عطل يُنتج حدثه.
- **الفعلي:** عند 120.0 ث: حدث واحد؛ عند 120.2 و121 و125 ث: حدثان. دورات RANDOM_FAULTS تبدأ بمضاعفات 30 ث تمامًا فتصيبها الحالة (QA-E2E-005b).
- **الدليل:** docs/evidence/full-qa/gate10b/same-kind-boundary.json؛ gate10/e2e05.json
- **السبب الجذري (مثبت/مشتبه):** في `EventRecorder.append_measurement` يُفحص المحفّز الجديد قبل إنهاء الأحداث المنتهية، والنافذة شاملة (`<= T+post_ms`).
- **الأثر على DoctorCAR:** فقد حدث/تقرير للعطل المتكرر في الدورة التالية مباشرة.
- **الملفات المتأثرة:** monitoring/event_recorder.py
- **الإصلاح المقترح:** أنهِ الأحداث المنتهية قبل تقييم المحفزات الجديدة أو اجعل الحد حصريًا؛ أضف اختبار حد.
- **اختبار Regression المطلوب:** QA-EVENT-016 + اختبار وحدة لحد T+30 (محفّز عند 120.0 ث يُنتج حدثًا مستقلًا)
- **هل يمنع اعتماد النموذج الأولي؟** نعم لعرض RANDOM_FAULTS/الدورات الدورية؛ لا للعرض بعطل منفرد
- **الحالة:** OPEN

## DEF-006 — المحاكي يوقف المحرك بعد ~150 ث ولا يكرر دورة القيادة؛ المدد الأطول بلا معنى

- **الخطورة:** MEDIUM
- **الفئة:** عيب محاكاة
- **المتطلب المتأثر:** SIM-003
- **خطوات إعادة الإنتاج:** شغّل `SimulationSource(duration_ms=600000, mode='RANDOM_FAULTS', ...)` (QA-SIM-037).
- **المتوقع:** جلسة محاكاة طويلة تحافظ على قيادة وتأثير أعطال الدورات الدورية.
- **الفعلي:** بعد 150 ث: RPM=0 حتى النهاية (2250 عينة)، و19 دورة أعطال مجدولة بلا أثر؛ جلسة 30 دقيقة أنتجت حدثين فقط.
- **الدليل:** docs/evidence/full-qa/gate8/results.json (QA-SIM-037)؛ gate8/long-run.json
- **السبب الجذري (مثبت/مشتبه):** ملف القيادة ثابت 155 ث؛ جدول الأعطال يغطي كامل المدة.
- **الأثر على DoctorCAR:** اختبار الجلسات الطويلة والدورات الدورية غير ممثل؛ المدة غير مكشوفة في الواجهة لكنها متاحة في API/CLI.
- **الملفات المتأثرة:** sources/simulation.py؛ sources/scenarios.py
- **الإصلاح المقترح:** كرّر دورة القيادة أو قيّد المدة القصوى برسالة؛ أو حقن الأعطال ضمن مدة تشغيل المحرك فقط.
- **اختبار Regression المطلوب:** QA-SIM-037: RPM>0 طوال المدة أو رفض المدد الأطول من الملف
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع (المدة غير مكشوفة في الواجهة)
- **الحالة:** OPEN

## DEF-007 — لا حدود صلاحية لغير المحاكاة: قيمة RPM=1e308 في ملف Replay تُخزَّن AVAILABLE دون علامة

- **الخطورة:** MEDIUM
- **الفئة:** عيب تطبيق (جودة البيانات)
- **المتطلب المتأثر:** FR-004 / DATA-001
- **خطوات إعادة الإنتاج:** شغّل `python audits/qa/qa_perf_neg.py` (QA-SEC-002) أو استبدل قيمة RPM في ملف Replay بـ1e308.
- **المتوقع:** تُعلَّم INVALID أو تُرفض مع حدث جودة.
- **الفعلي:** RPM=1e+308 مخزنة بجودة AVAILABLE، بلا أي حدث؛ ويمكن أن تغذي ML والتقارير.
- **الدليل:** docs/evidence/full-qa/gate8/negative-data.json؛ QA-SEC-002
- **السبب الجذري (مثبت/مشتبه):** `DEMO_BOUNDS` تُطبق فقط إذا كان المصدر/الأصل SIMULATION أو DEVICE_TEST (monitoring/data_quality.py).
- **الأثر على DoctorCAR:** ملفات إعادة التشغيل أو بروتوكول غير موسوم قد تدخل قيمًا مستحيلة.
- **الملفات المتأثرة:** monitoring/data_quality.py
- **الإصلاح المقترح:** أضف حدودًا فيزيائية مطلقة مستقلة عن المصدر (قيم واسعة) تُعلّم INVALID.
- **اختبار Regression المطلوب:** QA-SEC-002: RPM=1e308 في Replay يصبح INVALID مع حدث جودة
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع العرض بالمحاكاة؛ يمنع ادعاء حماية البيانات المستوردة
- **الحالة:** OPEN

## DEF-008 — Firmware يقبل غلاف HELLO ناقصًا (A07) — ما زال مفتوحًا

- **الخطورة:** MEDIUM
- **الفئة:** عيب Firmware
- **المتطلب المتأثر:** FR-013 / A07
- **خطوات إعادة الإنتاج:** قارن حقول `required` في المخطط بما يفحصه `handle_line` في device_protocol.c (QA-FW-003).
- **المتوقع:** التحقق من الحقول الثمانية الإلزامية قبل التنفيذ كما في Python.
- **الفعلي:** C يفحص protocol_version وtype فقط؛ لا device_id/session_id/sequence_number/timestamp_ms/source/payload.
- **الدليل:** docs/evidence/full-qa/gate9_fw/results.json؛ gate9/firmware-static-review.json
- **السبب الجذري (مثبت/مشتبه):** تحقق جزئي في `handle_line` (device_protocol.c:104–118).
- **الأثر على DoctorCAR:** عدم تطابق سلوك الجهاز مع المحلل؛ لا يمكن ادعاء توافق العتاد.
- **الملفات المتأثرة:** firmware/main/device_protocol.c
- **الإصلاح المقترح:** أضف التحقق الكامل ثم اختبار host للمحلل وبناء ESP-IDF (تكليف Firmware منفصل).
- **اختبار Regression المطلوب:** اختبار host للمحلل + QA-FW-003 + بناء ESP-IDF (تكليف Firmware منفصل)
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع العرض البرمجي؛ يمنع دمج العتاد
- **الحالة:** OPEN

## DEF-009 — رسائل الخطأ في الواجهة تعرض نص استثناء Python الخام (إنجليزي ومسارات داخلية) داخل جملة عربية

- **الخطورة:** MEDIUM
- **الفئة:** عيب تطبيق (واجهة)
- **المتطلب المتأثر:** UI-001 / NFR-001
- **خطوات إعادة الإنتاج:** مركز المصادر ← شبكة ← أدخل 999.999.1.1 ← فحص المصدر؛ أو Replay بملف غير موجود (QA-UI-014/015).
- **المتوقع:** رسالة محلية مفهومة بلغة الواجهة دون تفاصيل داخلية.
- **الفعلي:** «تعذر إكمال العملية: '999.999.1.1' does not appear to be an IPv4 or IPv6 address» و«…[Errno 2] No such file or directory: 'C:\Users\…'» و«Experimental TCP supports IPv4 loopback only; LAN is disabled».
- **الدليل:** docs/evidence/full-qa/gate2/results.json (QA-UI-014..016)
- **السبب الجذري (مثبت/مشتبه):** الواجهة تمرر نص الاستثناء مباشرة (worker/main_window).
- **الأثر على DoctorCAR:** تجربة مستخدم مختلطة اللغة وتكشف مسارات الجهاز.
- **الملفات المتأثرة:** ui/worker.py؛ ui/main_window.py؛ ui/localization.py
- **الإصلاح المقترح:** طابق الاستثناءات المعروفة برسائل مترجمة، وسجّل النص الخام في السجل فقط.
- **اختبار Regression المطلوب:** QA-UI-014/015: رسالة محلية بلا نص استثناء خام
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع
- **الحالة:** OPEN

## DEF-010 — بدء جلسة Replay دون مسار يعرض «Permission denied: '.'» المضلل

- **الخطورة:** LOW
- **الفئة:** عيب تطبيق (واجهة)
- **المتطلب المتأثر:** UI-001
- **خطوات إعادة الإنتاج:** مصدر Replay، اترك المسار فارغًا، اضغط بدء (QA-UI-016).
- **المتوقع:** «اختر ملف Replay».
- **الفعلي:** «تعذر إكمال العملية: [Errno 13] Permission denied: '.'».
- **الدليل:** docs/evidence/full-qa/gate2/results.json (QA-UI-016)
- **السبب الجذري (مثبت/مشتبه):** Path('') تتحول إلى '.'.
- **الأثر على DoctorCAR:** رسالة مضللة.
- **الملفات المتأثرة:** ui/main_window.py
- **الإصلاح المقترح:** تحقق من عدم فراغ المسار قبل الإرسال.
- **اختبار Regression المطلوب:** QA-UI-016: رسالة «اختر ملفًا» عند مسار فارغ
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع
- **الحالة:** OPEN

## DEF-011 — خلية DTC في جدول الحساسات تبقى عربية بعد التحويل إلى الإنجليزية (حتى وصول لقطة جديدة)

- **الخطورة:** LOW
- **الفئة:** عيب تطبيق (واجهة)
- **المتطلب المتأثر:** SETTINGS-001
- **خطوات إعادة الإنتاج:** شغّل جلسة، أوقفها، بدّل اللغة إلى EN، افتح قراءات الحساسات (ملف english-mode-arabic-text.json).
- **المتوقع:** كل نص الواجهة إنجليزي.
- **الفعلي:** الخلية تعرض «لا رمز مرصود» بالعربية.
- **الدليل:** docs/evidence/full-qa/gate2/english-mode-arabic-text.json
- **السبب الجذري (مثبت/مشتبه):** الخلية تُملأ عند وصول عينة ولا تُعاد ترجمتها عند تغيير اللغة.
- **الأثر على DoctorCAR:** عيب لغوي طفيف.
- **الملفات المتأثرة:** ui/main_window.py (جدول الحساسات)
- **الإصلاح المقترح:** أعد بناء الخلايا عند تغيير اللغة.
- **اختبار Regression المطلوب:** QA-UI-012 بعد جلسة موقوفة: لا نص عربي في وضع EN
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع
- **الحالة:** OPEN

## DEF-012 — Session لا يتحقق بنفسه من عمر التحليل (الحد في المحلل فقط)

- **الخطورة:** LOW
- **الفئة:** عيب تطبيق (ربط AI)
- **المتطلب المتأثر:** INT-003
- **خطوات إعادة الإنتاج:** QA-AI-LINK-003: محلل صوري يعيد تحليلًا عمره 8.2 ث.
- **المتوقع:** Session يرفضه أيضًا (دفاع متعدد الطبقات).
- **الفعلي:** Session ربطه كما هو؛ الحد 2000ms مطبق داخل `AnomalyAnalyzer.latest_before` فقط.
- **الدليل:** docs/evidence/full-qa/gate5_ai/results.json
- **السبب الجذري (مثبت/مشتبه):** منطق العمر داخل المحلل وحده.
- **الأثر على DoctorCAR:** لا أثر مع المحلل الحالي؛ خطر مع محللات مستقبلية.
- **الملفات المتأثرة:** core/session.py (_record_ai_status)
- **الإصلاح المقترح:** كرر التحقق في `_record_ai_status`.
- **اختبار Regression المطلوب:** QA-AI-LINK-003: تحليل عمره 8.2 ث يُرفض داخل Session
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع
- **الحالة:** OPEN

## DEF-013 — حساس مجهول في ملف Replay يُحفظ بقيمته (مع علامة UNSUPPORTED وحدث جودة) بينما يرفضه مستقبل TCP/Serial

- **الخطورة:** LOW
- **الفئة:** عيب تطبيق (جودة البيانات)
- **المتطلب المتأثر:** FR-004
- **خطوات إعادة الإنتاج:** QA-SEC-003.
- **المتوقع:** سلوك موحد (رفض أو تجاهل).
- **الفعلي:** FOO محفوظ بقيمته 1 وجودة UNSUPPORTED.
- **الدليل:** docs/evidence/full-qa/gate8/results.json
- **السبب الجذري (مثبت/مشتبه):** DataQualityValidator يعلّم المجهول ولا يحذفه.
- **الأثر على DoctorCAR:** تلوث بسيط لقاعدة البيانات ببيانات غير معرفة.
- **الملفات المتأثرة:** monitoring/data_quality.py؛ sources/replay.py
- **الإصلاح المقترح:** احذف الحساسات المجهولة من العينة المخزنة أو ارفضها.
- **اختبار Regression المطلوب:** QA-SEC-003: الحساس المجهول لا يُخزَّن بقيمته
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع
- **الحالة:** OPEN

## DEF-014 — التقرير الفني يكرر الفحص المقترح نفسه تحت كل فرضية

- **الخطورة:** LOW
- **الفئة:** عيب تقارير
- **المتطلب المتأثر:** DIAG-001
- **خطوات إعادة الإنتاج:** افتح التقرير الفني لأي حدث S01..S07 (docs/evidence/full-qa/gate6/reports/*-technical.txt).
- **المتوقع:** فحص واحد لكل فرضية أو قائمة موحدة.
- **الفعلي:** السطر نفسه «Check coolant level, fan…» مكرر.
- **الدليل:** docs/evidence/full-qa/gate6/diagnostic-review.json
- **السبب الجذري (مثبت/مشتبه):** كل فرضية تحمل نص الفحص نفسه.
- **الأثر على DoctorCAR:** ضجيج في التقرير الفني (المبسط يزيل التكرار).
- **الملفات المتأثرة:** diagnostics/human_report.py (render_technical)
- **الإصلاح المقترح:** اعرض الفحوص مرة واحدة أو اربط كل فحص بفرضيته.
- **اختبار Regression المطلوب:** فحص نصي: كل فحص يظهر مرة واحدة في التقرير الفني
- **هل يمنع اعتماد النموذج الأولي؟** لا يمنع
- **الحالة:** OPEN

---

# أخطاء سكربتات QA نفسها (ليست عيوب منتج)

لم تُعدَّل أي ملفات `results.json`. الفشلان المسجلان التاليان سببهما سكربت QA، وتصنيفهما النهائي في `adjudication.json` مع الدليل:

## QA-UI-039 — مسجَّل FAIL ← مُحكَّم BLOCKED

- **النوع:** QA-SCRIPT-ERROR (timing)
- **السبب:** The Replay source plays in recorded real time (documented). The script waited 60 s but the detection in the exported session is at 68.2 s.
- **الدليل:** gate2_controls/results.json (replay events=[]); scratch controls.sqlite3: REPLAY session STOPPED with 296 measurements, last timestamp 59000 ms (the detection time 68200 ms was never reached).
- **ما تحقق فعلًا:** Export (776 samples) -> browse dialog -> verify -> start Replay through the UI -> 296 samples ingested as a REPLAY session (all evidenced).
- **ما لم يتحقق:** Event detection during a UI-driven Replay. Indirect evidence only: the pytest suite (test_at014 export->Replay->event) passed in the baseline run; not a GUI test.

## QA-UI-041 — مسجَّل FAIL ← مُحكَّم PARTIAL

- **النوع:** QA-SCRIPT-ERROR (criterion)
- **السبب:** The pass criterion looked for the English stage name RECEIVING; the UI correctly shows localized Arabic stage names.
- **الدليل:** gate2_controls/results.json actual text: 'فحص ناجح / HELLO -> CAPABILITIES -> تصل البيانات / Firmware: software-tcp-1 | JSONL: 1', historical=2, status 'قيد التشغيل — DEVICE_TEST'; screenshot gate2_controls/screenshots/controls-verify-network.png; scratch DB holds 2 HISTORICAL events.
- **ما تحقق فعلًا:** Network source from the UI: host/port typed, verify succeeds with handshake stages, session runs, 2 historical events imported.
- **ما لم يتحقق:** The script's own English-string criterion (invalid); behaviour is evidenced by the recorded values above.

## سجل تصحيحات سكربتات QA أثناء الحملة

حالات أخفقت أو نجحت نجاحًا غير صالح بسبب السكربت، ثم صُحح السكربت (ولم يُمس المنتج):

| الاختبار | الحالة الأولى | السبب | السكربت المصحَّح |
| --- | --- | --- | --- |
| QA-UI-005 | FAIL | read the identifier column instead of the value column of the sensor table | audits/qa/qa_gui.py |
| QA-UI-010/011 | FAIL | QTest.mouseDClick alone is not registered as a double-click; click then double-click is what a user does | audits/qa/qa_gui.py |
| QA-EVENT-004/005/007/009 | FAIL | chosen scenarios produced no event (a real coverage gap, now DEF-003); scenarios changed to ones that do and the gap recorded as QA-EVENT-015 | audits/qa/qa_events_db.py |
| QA-DB-008 | FAIL | assumed a missing parent folder raises; the repository creates parent folders by design | audits/qa/qa_events_db.py |
| QA-IOT-007/010/011 | FAIL | the generated upload stream was cut after 400 messages, dropping later HELLO messages; the product correctly rejected it | audits/qa/qa_iot.py |
| QA-IOT-013 | FAIL | Windows reports a closed local port as TimeoutError (an OSError), not ConnectionRefusedError | audits/qa/qa_iot.py |
| QA-PERF-002 | PASS (invalid) | memory probe returned 0.0 MB because ctypes types were missing; the PASS was meaningless and was rebuilt with a working probe | audits/qa/qa_perf_neg.py |
| QA-PERF-001 | PASS (misleading) | a 30-minute single session was mostly a parked vehicle (DEF-006); rebuilt as 12 consecutive real trips | audits/qa/qa_perf_neg.py |
| QA-SEC-001 | FAIL | NaN was injected with a text pattern that did not match the compact JSON, so the line was unchanged | audits/qa/qa_perf_neg.py |
| QA-PKG-004 | FAIL | the 'development tree on sys.path' check matched the substring 'doccar' in the scratch venv path; now compares against the real project root | audits/qa/qa_installed_e2e.py, qa_package.py |
| QA-UI-033..038 | FAIL | spin-box test left severity at its minimum so no event existed; QCheckBox only reacts on its indicator; file dialog selectFile does not rename the default file; origin is stored in metadata_json | audits/qa/qa_gui_controls.py |
| QA-AI-LINK-003 | PASS (weak) | stub ignored age so the refusal was not demonstrated; reclassified PARTIAL and recorded as DEF-012 | audits/qa/qa_ai_diag.py |

# قيود البيئة (غير مختبر لهذا السبب)

- No ESP-IDF/CMake/Ninja/gcc: firmware build NOT TESTED
- No ESP32 board connected: USB, Wi-Fi, CAN, MicroSD, ADC/RTC NOT TESTED (and Wi-Fi/CAN/MicroSD/ADC/RTC are not implemented in M1)
- No OS-level UI Automation tool: interaction is QTest events inside the process; screenshots are QWidget.grab renders of the real window
- No line-coverage tool installed (the environment was not modified); coverage is functional, not line-based
- psutil not installed: memory measured with the Windows psapi working-set counter
- Visual review of every DPI/screen-reader scenario not performed
- Serial source tested with a fake port only

