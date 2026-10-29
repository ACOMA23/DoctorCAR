"""Writes docs/evidence/full-qa/defects.json (the defect register data). Every entry cites recorded evidence."""

import json
from pathlib import Path

D = []


def add(id_, sev, req, title, steps, expected, actual, evidence, cause, impact, fix):
    D.append(dict(id=id_, severity=sev, requirement=req, title=title, steps=steps, expected=expected, actual=actual,
                  evidence=evidence, cause=cause, impact=impact, fix=fix, status="OPEN"))


add("DEF-001", "HIGH", "AI-008 / AI-009 / INT-002", "ML يضيف إنذارات كاذبة دون زيادة في الكشف؛ دقة الدمج (قواعد+ML) أقل من القواعد وحدها",
    "شغّل `python audits/qa/qa_ml_eval.py` (52 رحلة مستقلة بذور 9000+) أو شغّل رحلات طبيعية في الواجهة بتفعيل AI.",
    "تفعيل ML لا يخفض الدقة، ويضيف كشفًا (أبكر أو أوسع) أو يبقى استشاريًا فقط.",
    "قواعد فقط: 27/28 أحداث و0 إنذار كاذب (دقة 1.00). ML v2: 5/28 و4 إنذارات كاذبة (1.79/ساعة). الدمج: 27/28 و4 كاذبة (دقة 0.897). ML v1: 13/28 و97 كاذبة (43/ساعة). كل ما اكتشفه ML اكتشفته القواعد أيضًا.",
    "docs/evidence/full-qa/gate5/ml-eval.json؛ ml-eval-alarms.csv؛ QA-AI-010",
    "IsolationForest يعزل أطراف توزيع الأطوار الطبيعية؛ القواعد مبنية على المولد نفسه فتبدو مثالية؛ معايرة العتبة تبادلت الاستدعاء بالإنذارات.",
    "أحداث ML المعروضة للمستخدم أغلبها كاذب أو مكرر للقواعد؛ يضعف الثقة بميزة AI.",
    "اجعل ML استشاريًا (لا يُنشئ حدثًا) أو اشترط تأييد قاعدة؛ أعد تقييم نموذج سياقي/معايرة على بيانات جديدة؛ أبلغ عن ML بشكل منفصل في التقرير.")
add("DEF-002", "HIGH", "AI-009", "إنذارات ML الكاذبة ما زالت قائمة في رحلات الإحماء مع معامل قيادة مرتفع (1.08–1.15)",
    "شغّل `qa_ml_eval.py` (مجموعة stress: 12 رحلة باردة) أو `AnomalyAnalyzer` على رحلة باردة بمعامل 1.14.",
    "لا إنذار ML في قيادة طبيعية.",
    "v2: 5 أحداث كاذبة في 5/12 رحلة (عند ~63–64 ث انتقال التسارع إلى السير)؛ v1: 32 إنذارًا في 12/12 رحلة. الحالة QA-AI-011 FAIL.",
    "docs/evidence/full-qa/gate5/ml-eval.json (stress_cold_high_scale)",
    "تغطية تدريبية/عتبة غير كافية لطرف توزيع معامل القيادة؛ لا ميزة سياق تشغيل.",
    "إنذار ML كاذب في ~40% من رحلات الإحماء المرتفعة؛ الواجهة لا تعرض معامل القيادة فلا يمكن إعادة إنتاجه يدويًا.",
    "أضف مدى معامل القيادة كاملًا وبدايات متنوعة للتدريب، ونموذجًا سياقيًا للإحماء، وقيّم على Test جديد؛ لا تغيّر الافتراضي دون مقارنة موثقة.")
add("DEF-003", "MEDIUM", "MS-RULE / MS-SIM", "فجوات في اكتشاف القواعد حسب الظرف والمدة",
    "شغّل `python audits/qa/qa_events_db.py` (QA-EVENT-015).",
    "كل عطل محقون إما يُنتج حدثًا أو تُوثَّق فجوته.",
    "25/35 تركيبة أنتجت حدثًا؛ لم تُكتشف: S01 وS02 وS03 وS04 بمدة 5 ث؛ وS02 وS03 وS04 عند البدء 110 ث (تباطؤ/خمول) و135 ث. كذلك flatline لـS07 (3/4 أحداث S07 في المجموعة المستقلة).",
    "docs/evidence/full-qa/gate4/detection-coverage.json؛ gate5/ml-eval.json",
    "شروط القواعد تتطلب محركًا يعمل بحمل/خانق ومدة كافية ومراجع صالحة.",
    "أعطال هواء/وقود في أطوار التباطؤ والخمول وقصيرة المدة لا تُسجَّل؛ الموثق في ملف التحكم 5 حالات فقط.",
    "وثّق الفجوات في README/ملف التحكم؛ أضف قواعد/نوافذ تناسب الخمول والتباطؤ؛ أضف حدث «مرجع غير كافٍ» حين تُعطَّل القاعدة.")
add("DEF-004", "MEDIUM", "MS-RULE / INT-002", "العطلان المتزامنان قد يخفي أحدهما الآخر: S04 لا يُكتشف عند وجود S07 flatline",
    "شغّل `python audits/qa/qa_masking.py` (QA-SIM-038).",
    "S04 يبقى مكتشفًا عند وجود عطل ثانٍ.",
    "S04 وحده: MS_AIRFLOW عند 66.2 ث. S04 + S07 flatline: لا أي حدث ولا تفسير.",
    "docs/evidence/full-qa/gate10b/masking.json",
    "قاعدة S04 تتطلب مرجع MAP صالحًا؛ تجميد ضغط السحب يُبطله فتُعطَّل القاعدة بصمت.",
    "يخفي عطلًا حقيقيًا عندما يتزامن مع عطل إشارة؛ يضلل المستخدم بغياب الإنذار.",
    "عند تعطيل قاعدة بسبب مرجع غير صالح أصدر حدث «لا يمكن التقييم» مع السبب؛ اختبر مصفوفة التركيبات.")
add("DEF-005", "MEDIUM", "FR-005", "عطل ثانٍ من النوع نفسه يبدأ عند حد T+30 بالضبط يُبتلع (لا حدث مستقل)",
    "شغّل `python audits/qa/qa_masking.py` (QA-EVENT-016): S07 dropout عند 90 ث ثم عند 120.0 ث.",
    "كل عطل يُنتج حدثه.",
    "عند 120.0 ث: حدث واحد؛ عند 120.2 و121 و125 ث: حدثان. دورات RANDOM_FAULTS تبدأ بمضاعفات 30 ث تمامًا فتصيبها الحالة (QA-E2E-005b).",
    "docs/evidence/full-qa/gate10b/same-kind-boundary.json؛ gate10/e2e05.json",
    "في `EventRecorder.append_measurement` يُفحص المحفّز الجديد قبل إنهاء الأحداث المنتهية، والنافذة شاملة (`<= T+post_ms`).",
    "فقد حدث/تقرير للعطل المتكرر في الدورة التالية مباشرة.",
    "أنهِ الأحداث المنتهية قبل تقييم المحفزات الجديدة أو اجعل الحد حصريًا؛ أضف اختبار حد.")
add("DEF-006", "MEDIUM", "SIM-003", "المحاكي يوقف المحرك بعد ~150 ث ولا يكرر دورة القيادة؛ المدد الأطول بلا معنى",
    "شغّل `SimulationSource(duration_ms=600000, mode='RANDOM_FAULTS', ...)` (QA-SIM-037).",
    "جلسة محاكاة طويلة تحافظ على قيادة وتأثير أعطال الدورات الدورية.",
    "بعد 150 ث: RPM=0 حتى النهاية (2250 عينة)، و19 دورة أعطال مجدولة بلا أثر؛ جلسة 30 دقيقة أنتجت حدثين فقط.",
    "docs/evidence/full-qa/gate8/results.json (QA-SIM-037)؛ gate8/long-run.json",
    "ملف القيادة ثابت 155 ث؛ جدول الأعطال يغطي كامل المدة.",
    "اختبار الجلسات الطويلة والدورات الدورية غير ممثل؛ المدة غير مكشوفة في الواجهة لكنها متاحة في API/CLI.",
    "كرّر دورة القيادة أو قيّد المدة القصوى برسالة؛ أو حقن الأعطال ضمن مدة تشغيل المحرك فقط.")
add("DEF-007", "MEDIUM", "FR-004 / DATA-001", "لا حدود صلاحية لغير المحاكاة: قيمة RPM=1e308 في ملف Replay تُخزَّن AVAILABLE دون علامة",
    "شغّل `python audits/qa/qa_perf_neg.py` (QA-SEC-002) أو استبدل قيمة RPM في ملف Replay بـ1e308.",
    "تُعلَّم INVALID أو تُرفض مع حدث جودة.",
    "RPM=1e+308 مخزنة بجودة AVAILABLE، بلا أي حدث؛ ويمكن أن تغذي ML والتقارير.",
    "docs/evidence/full-qa/gate8/negative-data.json؛ QA-SEC-002",
    "`DEMO_BOUNDS` تُطبق فقط إذا كان المصدر/الأصل SIMULATION أو DEVICE_TEST (monitoring/data_quality.py).",
    "ملفات إعادة التشغيل أو بروتوكول غير موسوم قد تدخل قيمًا مستحيلة.",
    "أضف حدودًا فيزيائية مطلقة مستقلة عن المصدر (قيم واسعة) تُعلّم INVALID.")
add("DEF-008", "MEDIUM", "FR-013 / A07", "Firmware يقبل غلاف HELLO ناقصًا (A07) — ما زال مفتوحًا",
    "قارن حقول `required` في المخطط بما يفحصه `handle_line` في device_protocol.c (QA-FW-003).",
    "التحقق من الحقول الثمانية الإلزامية قبل التنفيذ كما في Python.",
    "C يفحص protocol_version وtype فقط؛ لا device_id/session_id/sequence_number/timestamp_ms/source/payload.",
    "docs/evidence/full-qa/gate9_fw/results.json؛ gate9/firmware-static-review.json",
    "تحقق جزئي في `handle_line` (device_protocol.c:104–118).",
    "عدم تطابق سلوك الجهاز مع المحلل؛ لا يمكن ادعاء توافق العتاد.",
    "أضف التحقق الكامل ثم اختبار host للمحلل وبناء ESP-IDF (تكليف Firmware منفصل).")
add("DEF-009", "MEDIUM", "UI-001 / NFR-001", "رسائل الخطأ في الواجهة تعرض نص استثناء Python الخام (إنجليزي ومسارات داخلية) داخل جملة عربية",
    "مركز المصادر ← شبكة ← أدخل 999.999.1.1 ← فحص المصدر؛ أو Replay بملف غير موجود (QA-UI-014/015).",
    "رسالة محلية مفهومة بلغة الواجهة دون تفاصيل داخلية.",
    "«تعذر إكمال العملية: '999.999.1.1' does not appear to be an IPv4 or IPv6 address» و«…[Errno 2] No such file or directory: 'C:\\Users\\…'» و«Experimental TCP supports IPv4 loopback only; LAN is disabled».",
    "docs/evidence/full-qa/gate2/results.json (QA-UI-014..016)",
    "الواجهة تمرر نص الاستثناء مباشرة (worker/main_window).",
    "تجربة مستخدم مختلطة اللغة وتكشف مسارات الجهاز.",
    "طابق الاستثناءات المعروفة برسائل مترجمة، وسجّل النص الخام في السجل فقط.")
add("DEF-010", "LOW", "UI-001", "بدء جلسة Replay دون مسار يعرض «Permission denied: '.'» المضلل",
    "مصدر Replay، اترك المسار فارغًا، اضغط بدء (QA-UI-016).", "«اختر ملف Replay».", "«تعذر إكمال العملية: [Errno 13] Permission denied: '.'».",
    "docs/evidence/full-qa/gate2/results.json (QA-UI-016)", "Path('') تتحول إلى '.'.", "رسالة مضللة.", "تحقق من عدم فراغ المسار قبل الإرسال.")
add("DEF-011", "LOW", "SETTINGS-001", "خلية DTC في جدول الحساسات تبقى عربية بعد التحويل إلى الإنجليزية (حتى وصول لقطة جديدة)",
    "شغّل جلسة، أوقفها، بدّل اللغة إلى EN، افتح قراءات الحساسات (ملف english-mode-arabic-text.json).", "كل نص الواجهة إنجليزي.", "الخلية تعرض «لا رمز مرصود» بالعربية.",
    "docs/evidence/full-qa/gate2/english-mode-arabic-text.json", "الخلية تُملأ عند وصول عينة ولا تُعاد ترجمتها عند تغيير اللغة.", "عيب لغوي طفيف.", "أعد بناء الخلايا عند تغيير اللغة.")
add("DEF-012", "LOW", "INT-003", "Session لا يتحقق بنفسه من عمر التحليل (الحد في المحلل فقط)",
    "QA-AI-LINK-003: محلل صوري يعيد تحليلًا عمره 8.2 ث.", "Session يرفضه أيضًا (دفاع متعدد الطبقات).",
    "Session ربطه كما هو؛ الحد 2000ms مطبق داخل `AnomalyAnalyzer.latest_before` فقط.", "docs/evidence/full-qa/gate5_ai/results.json",
    "منطق العمر داخل المحلل وحده.", "لا أثر مع المحلل الحالي؛ خطر مع محللات مستقبلية.", "كرر التحقق في `_record_ai_status`.")
add("DEF-013", "LOW", "FR-004", "حساس مجهول في ملف Replay يُحفظ بقيمته (مع علامة UNSUPPORTED وحدث جودة) بينما يرفضه مستقبل TCP/Serial",
    "QA-SEC-003.", "سلوك موحد (رفض أو تجاهل).", "FOO محفوظ بقيمته 1 وجودة UNSUPPORTED.", "docs/evidence/full-qa/gate8/results.json",
    "DataQualityValidator يعلّم المجهول ولا يحذفه.", "تلوث بسيط لقاعدة البيانات ببيانات غير معرفة.", "احذف الحساسات المجهولة من العينة المخزنة أو ارفضها.")
add("DEF-014", "LOW", "DIAG-001", "التقرير الفني يكرر الفحص المقترح نفسه تحت كل فرضية",
    "افتح التقرير الفني لأي حدث S01..S07 (docs/evidence/full-qa/gate6/reports/*-technical.txt).", "فحص واحد لكل فرضية أو قائمة موحدة.",
    "السطر نفسه «Check coolant level, fan…» مكرر.", "docs/evidence/full-qa/gate6/diagnostic-review.json",
    "كل فرضية تحمل نص الفحص نفسه.", "ضجيج في التقرير الفني (المبسط يزيل التكرار).", "اعرض الفحوص مرة واحدة أو اربط كل فحص بفرضيته.")

EXTRA = {
    "DEF-001": ("عيب AI", "analysis/analyzer.py؛ core/session.py (دمج حدث ML)؛ analysis/models/*", "qa_ml_eval.py على 52 رحلة جديدة: إنذارات الدمج الكاذبة <= القواعد وحدها وrecall الدمج >= القواعد", "لا يمنع عرض المسار الكامل؛ يمنع ادعاء قيمة مضافة لـAI ما لم يُعلن ML استشاريًا"),
    "DEF-002": ("عيب AI", "analysis/benchmark.py؛ analysis/windows.py؛ analysis/models/*", "مجموعة stress (12 رحلة باردة بمعامل 1.08-1.15): صفر إنذار ML، مع اختبار pytest للمعاملات القصوى", "لا يمنع العرض بقواعد فقط؛ يلزم إصلاحه أو الإفصاح قبل عرض AI أمام لجنة"),
    "DEF-003": ("عيب تطبيق (محرك القواعد)", "monitoring/evidence_rules.py؛ monitoring/event_detector.py", "مصفوفة QA-EVENT-015 (35 تركيبة): كل تركيبة تُنتج حدثًا أو حدث «تعذر التقييم»", "لا يمنع؛ يجب الإفصاح عن الفجوات"),
    "DEF-004": ("عيب تطبيق (محرك القواعد)", "monitoring/evidence_rules.py", "QA-SIM-038: S04 يبقى مكتشفًا مع S07 flatline أو يصدر حدث «تعذر التقييم»", "لا يمنع العرض بأعطال منفردة؛ يمنع ادعاء كشف الأعطال المتزامنة"),
    "DEF-005": ("عيب تطبيق (مسجل الأحداث)", "monitoring/event_recorder.py", "QA-EVENT-016 + اختبار وحدة لحد T+30 (محفّز عند 120.0 ث يُنتج حدثًا مستقلًا)", "نعم لعرض RANDOM_FAULTS/الدورات الدورية؛ لا للعرض بعطل منفرد"),
    "DEF-006": ("عيب محاكاة", "sources/simulation.py؛ sources/scenarios.py", "QA-SIM-037: RPM>0 طوال المدة أو رفض المدد الأطول من الملف", "لا يمنع (المدة غير مكشوفة في الواجهة)"),
    "DEF-007": ("عيب تطبيق (جودة البيانات)", "monitoring/data_quality.py", "QA-SEC-002: RPM=1e308 في Replay يصبح INVALID مع حدث جودة", "لا يمنع العرض بالمحاكاة؛ يمنع ادعاء حماية البيانات المستوردة"),
    "DEF-008": ("عيب Firmware", "firmware/main/device_protocol.c", "اختبار host للمحلل + QA-FW-003 + بناء ESP-IDF (تكليف Firmware منفصل)", "لا يمنع العرض البرمجي؛ يمنع دمج العتاد"),
    "DEF-009": ("عيب تطبيق (واجهة)", "ui/worker.py؛ ui/main_window.py؛ ui/localization.py", "QA-UI-014/015: رسالة محلية بلا نص استثناء خام", "لا يمنع"),
    "DEF-010": ("عيب تطبيق (واجهة)", "ui/main_window.py", "QA-UI-016: رسالة «اختر ملفًا» عند مسار فارغ", "لا يمنع"),
    "DEF-011": ("عيب تطبيق (واجهة)", "ui/main_window.py (جدول الحساسات)", "QA-UI-012 بعد جلسة موقوفة: لا نص عربي في وضع EN", "لا يمنع"),
    "DEF-012": ("عيب تطبيق (ربط AI)", "core/session.py (_record_ai_status)", "QA-AI-LINK-003: تحليل عمره 8.2 ث يُرفض داخل Session", "لا يمنع"),
    "DEF-013": ("عيب تطبيق (جودة البيانات)", "monitoring/data_quality.py؛ sources/replay.py", "QA-SEC-003: الحساس المجهول لا يُخزَّن بقيمته", "لا يمنع"),
    "DEF-014": ("عيب تقارير", "diagnostics/human_report.py (render_technical)", "فحص نصي: كل فحص يظهر مرة واحدة في التقرير الفني", "لا يمنع"),
}
for entry in D:
    cat, files, regression, blocks = EXTRA[entry["id"]]
    entry.update(category=cat, files=files, regression=regression, blocks_prototype=blocks)

out = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "full-qa" / "defects.json"
out.write_text(json.dumps(D, ensure_ascii=False, indent=2), encoding="utf8")
print(len(D), "defects written to", out)
