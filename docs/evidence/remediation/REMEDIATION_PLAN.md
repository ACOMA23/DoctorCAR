# DC-FIX-001 — خطة المعالجة (كما نُفِّذت)

المرجع: `docs/evidence/full-qa/DEFECT_REGISTER.md` (14 عيبًا). نسخة احتياطية للمصادر قبل التعديل في مساحة الجلسة المؤقتة، وبصمات ما قبل التعديل في `gate0/before.sha`. لم تُمَس `data/doctorcar.sqlite3` ولا نتائج QA التاريخية (`docs/evidence/full-qa/*`).

| البوابة | العيوب | معيار القبول (حُدد قبل التنفيذ) | الملفات |
| --- | --- | --- | --- |
| 1 سلامة القراءات | DEF-007، DEF-013 | قيمة مستحيلة (RPM=1e308…) لا تُخزَّن AVAILABLE من أي مصدر؛ حساس مجهول لا يدخل تيار القراءات ويُبلَّغ عنه | `monitoring/data_quality.py` |
| 2 دورة حياة الحدث | DEF-005، DEF-012 | عطل جديد من النوع نفسه عند T+30 بالضبط يأخذ حدثه؛ التكرار داخل النافذة لا يُنتج نسخة؛ Session يرفض تحليلًا قديمًا/مستقبليًا/من جلسة أخرى | `monitoring/event_recorder.py`، `core/session.py` |
| 3 الأعطال المتزامنة | DEF-004، DEF-003 | S04 لا يُخفى بتجميد MAP؛ تجميد MAP نفسه يُكتشف؛ صفر أحداث على رحلات سليمة؛ الفجوات غير القابلة للتمييز موثقة | `monitoring/evidence_rules.py` |
| 4 استمرارية المحاكاة | DEF-006 | جلسة أطول من 155 ث لا يتوقف محركها؛ الرحلة الافتراضية متطابقة بتًّا مع السابقة | `sources/simulation.py` |
| 5 ML | DEF-001، DEF-002 | ML-only لا يفتح حدثًا في التطبيق؛ النموذج الافتراضي لا يزيد الإنذارات الكاذبة على Test مستقل؛ لا بيانات QA السابقة في التدريب | `core/session.py`، `ui/worker.py`، `analysis/benchmark.py`، `analysis/model.py`، `analysis/models/cr006-iforest-v3/` |
| 6 XAI | — | تفسير من النموذج نفسه، رفض نموذج آخر/مدخل مُتلاعب به | اختبارات فقط |
| 7 الواجهة | DEF-009، 010، 011، 014 | لا نص استثناء خام؛ مسار Replay فارغ يطلب ملفًا؛ DTC يتبع اللغة؛ فحص مكرر يُذكر مرة | `ui/worker.py`، `ui/main_window.py`، `ui/localization.py`، `diagnostics/reports.py` |
| 7 Firmware | DEF-008 | Patch مقترح فقط (لا بناء) — غير VERIFIED | `gate7_firmware/*` |

الاختبارات الجديدة: `desktop/tests/cr006/` (87 اختبارًا). سكربتات الأدلة: `audits/remediation/`.
