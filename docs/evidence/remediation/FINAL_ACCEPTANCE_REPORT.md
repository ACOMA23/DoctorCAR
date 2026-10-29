# DC-FIX-001 — تقرير القبول النهائي

**القرار: PARTIAL.** النظام أفضل وأكثر موثوقية، لكن لا يُعلن PASS: عيبان جزئيان وعيب Firmware مفتوح، والواجهة الأصلية الكاملة لم تُعَد اختباراتها.

## 1–3. العيوب
الأصلية 14. المصححة والمثبتة 11 (DEF-001*, 004*, 005, 006, 007, 009, 010, 011, 012, 013, 014؛ * بحدود). المتبقية 3: DEF-002 وDEF-003 (PARTIAL)، DEF-008 (OPEN — Patch مقترح غير مبني). الحالة لكل عيب بالسبب والتعديل والدليل في [FIX_VERIFICATION_MATRIX.md](FIX_VERIFICATION_MATRIX.md).

## 4. ملفات الكود المعدلة
`monitoring/{data_quality,event_recorder,evidence_rules}.py`، `core/session.py`، `sources/simulation.py`، `analysis/{benchmark,model}.py` + نموذج جديد `analysis/models/cr006-iforest-v3/`، `diagnostics/reports.py`، `ui/{worker,main_window,localization}.py`. اختبارات CR-005 عُدّلت في 3 تأكيدات (اسم النموذج الافتراضي وعدد النماذج المحزومة). `audits/qa/qa_common.py` (متغير `QA_EVIDENCE` فقط). جديد: `desktop/tests/cr006/` (87)، `audits/remediation/` (3 سكربتات). بصمات ما قبل التعديل: [gate0/before.sha](gate0/before.sha).

## 5. الاختبارات قبل وبعد
قبل: 193 passed (خط أساس DC-CR-005) + حملة QA (174 حالة: 152 PASS / 6 FAIL / 9 PARTIAL / 1 BLOCKED / 6 NOT TESTED بعد التحكيم). بعد: **280 passed / 0 failed / 0 skipped** (124 ث، exit 0؛ [full-suite.log](gate9/full-suite.log)). اختبارات cr006 الجديدة تفشل على المصدر القديم: Gate1 15، Gate2 3+3، Gate3 (استيراد/سلوك)، Gate4 3.
Ruff/format على `desktop/src` و`desktop/tests/cr006` و`audits/remediation`: نظيفة؛ mypy: نظيف (49 ملفًا)؛ pip check: نظيف. (`audits/qa/*` لم يُنسَّق: سكربتات حملة QA التاريخية.)

## 6. حالة كل عيب
DEF-001 CLOSED* · DEF-002 PARTIAL · DEF-003 PARTIAL · DEF-004 CLOSED* · DEF-005 CLOSED · DEF-006 CLOSED · DEF-007 CLOSED · DEF-008 OPEN · DEF-009 CLOSED · DEF-010 CLOSED · DEF-011 CLOSED · DEF-012 CLOSED · DEF-013 CLOSED · DEF-014 CLOSED.

## 7–8. ML والإنذارات الكاذبة والكشف
انظر [ML_BEFORE_AFTER.md](ML_BEFORE_AFTER.md). Test مستقل (76 رحلة، 40 حدثًا): قواعد 40/40 بلا إنذار كاذب؛ ML v2 استدعاء 0.175 مع 7 كاذبة؛ **v3 استدعاء 0.075 مع 0 كاذبة**؛ دمج v3 = القواعد. ضغط طازج بارد/معامل عالٍ: v2 10/15 رحلة، v3 1/15. سياسة التطبيق: ML استشاري لا يفتح حدثًا بمفرده. ML لا يضيف كشفًا.

## 9. XAI
`test_gate6_xai.py` (4): التفسير من النموذج نفسه (SHA)، يعيد الدرجة المخزنة بدقة 1e-12، يرفض نموذجًا آخر ودرجة مُتلاعبًا بها ومدخلًا ناقصًا وschema مختلفًا، يميز المجموعات التي لا يقرؤها النموذج، لا ينتج تفسيرًا لرحلة سليمة (لا إنذار). تفاسير cr005 القائمة ما زالت ناجحة. لا ادعاء سبب ميكانيكي.

## 10. المحاكاة والأحداث
جلسة 600 ث: 3001 عينة بمحور زمني متصل ومحرك لا يتوقف (الرحلة 155 ث الافتراضية متطابقة بتًّا). حدث عند T+30 يُسجَّل (120.0/120.2/121/125 ث → حدثان). أعطال متزامنة: 7/7 تركيبة قابلة للحقن تحتفظ بكلا الكشفين (14 زوجًا منها لا يحقنها المحاكي لتعارض الكتابة)؛ 0 أحداث على 30 رحلة سليمة. التغطية 25/35 (لم تتغير؛ موثقة).

## 11. الواجهة الحقيقية
اختبارات نافذة offscreen (رسائل الخطأ، مسار فارغ، لغة DTC) + إعادة تشغيل `qa_perf_neg.py` (12 PASS، فيها QA-UI-020..023 على النافذة) + نافذة أصلية من الحزمة المثبتة (QA-E2E-012b PASS). **إعادة الاختبار الأصلي الكامل لعناصر الواجهة (qa_gui/qa_gui_controls) لم تُجرَ → NOT RE-RUN.**

## 12. التثبيت النظيف
`qa-rerun/gate9`: 7/7 PASS (wheel، venv جديد مع قفل الاعتماديات، pip check، نقطة الدخول، تحميل v1/v2/v3، محاكاة وAI وتقرير، نافذة أصلية).

## 13. IoT
حزمة الاختبارات الكاملة (cr002 وTCP loopback والمحاكي) ضمن الـ280 ناجحة. لم تُعَد `qa_iot.py` منفصلة.

## 14. Firmware
لم يتغير (بصمات مطابقة). A07: [Patch مقترح](gate7_firmware/A07_envelope_validation.patch) وخطة اختبار؛ **NOT BUILT / NOT VERIFIED**.

## 15. العدّ
إعادة التشغيل المستهدفة (سجل منفصل `gate9/qa-rerun/*/results.json`): gate10b 3 PASS؛ gate8 12 PASS / 1 FAIL (QA-SEC-003 بمعيار متقادم عمدًا) / 1 PARTIAL؛ gate4 23 PASS / 1 BLOCKED (يحتاج قاعدة GUI من gate2) / 1 PARTIAL (QA-EVENT-015)؛ gate9 7 PASS. حالات الفشل الستة الأصلية: SIM-037 PASS، SEC-002 PASS، SIM-038 PASS، EVENT-016 PASS، AI-011 مغطاة بمجموعة الضغط (v3: 0/12؛ طازجة 1/15 → PARTIAL)، FW-003 باقية FAIL. بقية الـ174 لم تُعَد → NOT RE-RUN (لا ادعاء عدّ إجمالي جديد). pytest: 280 PASS / 0 FAIL / 0 SKIP.

## 16. Regression
لا Regression وظيفيًا. تغييران سلوكيان مقصودان أثّرا على معايير قديمة: QA-SEC-003 (الحساس المجهول يُحذف الآن)، وثلاثة تأكيدات CR-005 عن النموذج الافتراضي.

## 17. تحقق يدوي (PowerShell من `C:\doccar`)
```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -c desktop/pyproject.toml desktop/tests audits/test_m1_acceptance.py -q -p no:cacheprovider --basetemp=data/claude-tests
.\.venv\Scripts\python.exe -B audits\remediation\rules_matrix.py
.\.venv\Scripts\python.exe -B audits\remediation\ml_stress.py
.\.venv\Scripts\python.exe -m doctorcar
```
في الواجهة: مصدر Replay بمسار فارغ ثم «ابدأ» (رسالة اختيار ملف)؛ بدّل اللغة أثناء التشغيل وانظر خلية DTC؛ محاكاة مترابطة S04+S07 (flatline) وتحقق من الحدثين.

## 18. القرار النهائي: **PARTIAL**
