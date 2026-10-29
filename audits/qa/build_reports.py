"""Builds QA_MASTER_PLAN.md, DEFECT_REGISTER.md and TEST_INVENTORY.json from the recorded results.
Statuses are computed from results.json files; nothing here marks a test as PASS by hand."""

import ast
import json
import platform
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, ROOT  # noqa: E402

cases = {}
gate_of = {}
for p in sorted(EVIDENCE.glob("*/results.json")):
    data = json.loads(p.read_text("utf8"))
    for c in data["cases"]:
        cases[c["test_id"]] = c
        gate_of[c["test_id"]] = data["gate"]
counts = Counter(c["status"] for c in cases.values())
ADJ = json.loads((EVIDENCE / "adjudication.json").read_text("utf8")) if (EVIDENCE / "adjudication.json").exists() else {}
adj = ADJ.get("adjudicated", {})
adj_counts = Counter(adj[t]["adjudicated_status"] if t in adj else c["status"] for t, c in cases.items())


def status_of(ids, override=None):
    if override:
        return override
    sts = [adj[i]["adjudicated_status"] if i in adj else cases[i]["status"] for i in ids if i in cases]
    missing = [i for i in ids if i not in cases]
    if not sts:
        return "Not Tested"
    if "FAIL" in sts:
        return "Failed" if all(s == "FAIL" for s in sts) else "Partially Verified"
    if "PARTIAL" in sts:
        return "Partially Verified"
    if all(s == "NOT TESTED" for s in sts):
        return "Not Tested"
    if missing:
        return "Partially Verified"
    return "Verified" if all(s == "PASS" for s in sts) else "Partially Verified"


R = lambda *ids: list(ids)  # noqa: E731
INVENTORY = [
    ("APP", "Application launch on the native Windows platform", R("QA-APP-001", "QA-E2E-012b")),
    ("APP", "Console entry point (doctorcar --help)", R("QA-PKG-005")),
    ("UI", "Sidebar navigation: 6 pages", R("QA-UI-002", "QA-UI-030")),
    ("UI", "Source center: fields shown per source / mode / family", R("QA-UI-003", "QA-UI-004")),
    ("UI", "Combo boxes (9): all items selectable", R("QA-UI-031")),
    ("UI", "Spin boxes (7): range clamping and keyboard", R("QA-UI-032")),
    ("UI", "Text fields and AI check box", R("QA-UI-033")),
    ("UI", "Start / Stop buttons, source locking, second-session refusal", R("QA-UI-005", "QA-UI-006", "QA-UI-009", "QA-UI-020")),
    ("UI", "Live sensor table updates", R("QA-UI-005", "QA-SENSOR-003")),
    ("UI", "AI status card (state, score, model version)", R("QA-UI-008")),
    ("UI", "Event list and 'تحديث السجل' button", R("QA-UI-034")),
    ("UI", "Open an event report (double-click and button)", R("QA-UI-010", "QA-UI-035")),
    ("UI", "Technical details toggle and time-series plot", R("QA-UI-011")),
    ("UI", "Verify source / connection button", R("QA-UI-038", "QA-UI-041", "QA-UI-014", "QA-UI-015")),
    ("UI", "Browse file dialog (real dialog)", R("QA-UI-037")),
    ("UI", "Export session to Replay (real dialog) and Replay from the UI", R("QA-UI-036", "QA-UI-039")),
    ("UI", "Refresh serial ports button", R("QA-UI-040")),
    ("UI", "Arabic/English, RTL/LTR, no leftover Arabic in English mode", R("QA-UI-012", "QA-UI-013")),
    ("UI", "Light / Dark theme and settings persistence across restart", R("QA-UI-018", "QA-E2E-011")),
    ("UI", "Window close shuts the worker down", R("QA-UI-017")),
    ("UI", "Responsiveness during a running session", R("QA-UI-007", "QA-PERF-006")),
    ("UI", "No stale live data after restart", R("QA-UI-019")),
    ("UI", "Error messages for invalid input", R("QA-UI-014", "QA-UI-015", "QA-UI-016", "QA-UI-023")),
    ("UI", "Menu bar", [], "Not Implemented"),
    ("UI", "Keyboard shortcuts", [], "Not Implemented"),
    ("UI", "System theme mode", [], "Not Implemented"),
    ("SENSOR", "Sensor registry (12 entries, units)", R("QA-SENSOR-001")),
    ("SENSOR", "Reading type, unit, quality and timing over a full trip", R("QA-SENSOR-002")),
    ("SENSOR", "Value-exact chain: simulation -> Session -> SQLite", R("QA-SENSOR-003")),
    ("SENSOR", "Validator: missing / unsupported / range / stale / duplicate / backward", R("QA-SENSOR-004")),
    ("SENSOR", "Operating relations across cold/warm/scale variants", R("QA-SENSOR-005", "QA-SENSOR-006")),
    ("SIM", "Determinism by seed and trip length", R("QA-SIM-001", "QA-SIM-002")),
    ("SIM", "Fault scenarios S01..S07: affected sensors and direction", R("QA-SIM-011", "QA-SIM-012", "QA-SIM-013", "QA-SIM-014", "QA-SIM-015", "QA-SIM-016", "QA-SIM-017", "QA-SIM-030", "QA-SIM-031", "QA-SIM-032")),
    ("SIM", "Fault durations (5 s, 90 s) and recovery", R("QA-SIM-033", "QA-SIM-034")),
    ("SIM", "Simultaneous faults and conflict rejection", R("QA-SIM-035")),
    ("SIM", "RANDOM_FAULTS 30 s cycles and ground-truth schedule", R("QA-SIM-036", "QA-E2E-005")),
    ("SIM", "Simulation longer than the 155 s driving profile", R("QA-SIM-037")),
    ("EVENT", "T-30 / T+30 recording at 1 Hz, 5 Hz, irregular and with missing samples", R(*[f"QA-EVENT-{i:03d}" for i in (1, 2, 3, 4, 5, 6, 10, 13, 14)])),
    ("EVENT", "Edge cases: trip start, trip end (PARTIAL), disappearing fault, manual stop", R("QA-EVENT-007", "QA-EVENT-008", "QA-EVENT-009", "QA-EVENT-011", "QA-E2E-004")),
    ("EVENT", "Recovery after abrupt close", R("QA-EVENT-012", "QA-E2E-008")),
    ("EVENT", "Rule detection coverage by condition", R("QA-EVENT-015")),
    ("DB", "Schema, pragmas, integrity, foreign keys", R("QA-DB-001", "QA-DB-002", "QA-DB-005")),
    ("DB", "Reports stored and restored, duplicates, reopen", R("QA-DB-003", "QA-DB-004", "QA-DB-006")),
    ("DB", "Old (v1) database upgrade and future-version refusal", R("QA-DB-007")),
    ("DB", "Write failure, corrupt file, unavailable path (library and window)", R("QA-DB-008", "QA-DB-009")),
    ("DB", "Language/theme changes leave stored data untouched", R("QA-DB-010")),
    ("AI", "Model facts, trusted loading", R("QA-AI-001", "QA-AI-002")),
    ("AI", "Determinism, window cases, no future leakage, no label use", R("QA-AI-003", "QA-AI-004", "QA-AI-005", "QA-AI-006")),
    ("AI", "ML performance: Rules vs ML vs Combined (window and event level)", R("QA-AI-010", "QA-AI-011", "QA-AI-007", "QA-AI-008")),
    ("XAI", "Explanations: deterministic, independent recomputation, safeguards", R("QA-XAI-001", "QA-XAI-002", "QA-XAI-003", "QA-XAI-004")),
    ("AI", "AI-to-event linking and AI state reporting", R("QA-AI-LINK-001", "QA-AI-LINK-002", "QA-AI-LINK-003", "QA-AI-LINK-004", "QA-AI-LINK-005", "QA-AI-LINK-006")),
    ("DIAG", "Evidence-based reports for S01..S07 and ambiguity handling", R(*[f"QA-DIAG-S0{i}" for i in range(1, 8)], "QA-DIAG-AMBIG")),
    ("IOT", "Protocol conformance and malformed input", R(*[f"QA-IOT-{i:03d}" for i in (1, 2, 3, 4, 5, 6, 9, 12)])),
    ("IOT", "Historical event upload, integrity and de-duplication", R("QA-IOT-007", "QA-IOT-008", "QA-IOT-010", "QA-IOT-011", "QA-E2E-007")),
    ("IOT", "TCP loopback failures: refused, silent, closed, oversized, bad config", R("QA-IOT-013", "QA-IOT-014", "QA-IOT-015", "QA-IOT-016", "QA-IOT-017")),
    ("IOT", "Serial source with a fake port (never writes)", R("QA-IOT-018", "QA-IOT-019")),
    ("IOT", "Live loopback device, reconnect and isolation", R("QA-E2E-006", "QA-E2E-010", "QA-IOT-020")),
    ("PERF", "Long run, memory, XAI/ML latency, event persistence", R("QA-PERF-001", "QA-PERF-002", "QA-PERF-003", "QA-PERF-004")),
    ("SEC", "Invalid data handling in replay files", R("QA-SEC-001", "QA-SEC-002", "QA-SEC-003")),
    ("PKG", "Wheel, fresh install, installed run, entry point", R("QA-PKG-001", "QA-PKG-002", "QA-PKG-003", "QA-PKG-004", "QA-PKG-005", "QA-E2E-012", "QA-E2E-012b")),
    ("FW", "Firmware build (ESP-IDF)", R("QA-FW-001")),
    ("FW", "Firmware static review: target, CAN guard, buffers, test mode, errors", R("QA-FW-002", "QA-FW-004", "QA-FW-005", "QA-FW-006", "QA-FW-007")),
    ("FW", "Firmware envelope validation (A07)", R("QA-FW-003")),
    ("FW", "Hardware: USB, Wi-Fi, CAN, MicroSD, ADC/RTC on a board", R("QA-FW-008", "QA-FW-009", "QA-FW-010", "QA-FW-011", "QA-FW-012")),
    ("E2E", "E2E-01..03, 09: normal, thermal, air/fuel, ML+XAI through the app", R("QA-E2E-001", "QA-E2E-002", "QA-E2E-003", "QA-E2E-009")),
]
inventory = []
for item in INVENTORY:
    area, name, ids = item[0], item[1], item[2]
    override = item[3] if len(item) > 3 else None
    inventory.append({"area": area, "function": name, "tests": ids, "status": status_of(ids, override)})
inv_counts = Counter(i["status"] for i in inventory)
(EVIDENCE / "TEST_INVENTORY.json").write_text(json.dumps({"summary": inv_counts, "items": inventory}, ensure_ascii=False, indent=2), encoding="utf8")

# public callables in the product (for the "how many functions exist" question)
funcs = Counter()
for f in (ROOT / "desktop" / "src" / "doctorcar").rglob("*.py"):
    tree = ast.parse(f.read_text("utf8"))
    pkg = f.relative_to(ROOT / "desktop" / "src" / "doctorcar").parts[0] if len(f.relative_to(ROOT / "desktop" / "src" / "doctorcar").parts) > 1 else "(root)"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            funcs[pkg] += 1
        elif isinstance(node, ast.FunctionDef) and node.name in ("__init__", "__post_init__"):
            funcs[pkg] += 0

DEFECTS = json.loads((EVIDENCE / "defects.json").read_text("utf8")) if (EVIDENCE / "defects.json").exists() else []

# ---------------------------------------------------------------------------- master plan
by_req = defaultdict(list)
for c in cases.values():
    for r in [x.strip() for x in c["requirement"].replace(";", "/").split("/") if x.strip()]:
        by_req[r].append(c["test_id"])
lines = ["# DoctorCAR — QA Master Plan (DC-QA-001)", "",
         "نوع المستند: خطة اختبار ونتائجها الفعلية. كل حالة هنا لها ملف نتائج (`results.json`) تحت `docs/evidence/full-qa/<gate>/`؛ ولا تُسجَّل PASS دون مخرج فعلي مطابق لمعيار نجاح محدد.", "",
         "## 1. الأهداف", "",
         "1. التحقق من سلوك التطبيق الحقيقي (واجهة Windows الأصلية) لا الكود وحده.", "2. التحقق من صحة القراءات وعلاقات الحساسات ودقة تأثير الأعطال المحقونة.", "3. التحقق من الكشف (قواعد/ML)، XAI، التقارير، التسجيل T±30، قاعدة SQLite.",
         "4. التحقق من IoT والبروتوكول والتثبيت على بيئة نظيفة، ومراجعة Firmware ساكنًا.", "5. تسجيل العيوب بخطوات إعادة الإنتاج وخطة إصلاح قابلة للتنفيذ.", "",
         "## 2. النطاق وما خارجه", "",
         "**داخل النطاق:** تطبيق `doctorcar` 0.1.0 (Python/PySide6)، النموذجان v1/v2 (الافتراضي v2)، المحاكي، البروتوكول، SQLite، الحزمة، مصدر Firmware (قراءة).",
         "**خارج النطاق/غير ممكن هنا:** بناء Firmware (لا ESP-IDF)، أي لوحة أو مركبة أو CAN أو Wi-Fi أو MicroSD، اختبار بصري يدوي طويل على أحجام DPI متعددة، قارئ الشاشة.", "",
         "## 3. الإصدارات والبيئة", "",
         f"- التطبيق: doctorcar 0.1.0؛ النموذج الافتراضي `cr005-iforest-v2` (sha256 03153e0d…d85d87)؛ v1 `cr004-iforest-v1` (0970cd00…97a7).",
         f"- Python {sys.version.split()[0]}، {platform.platform()}، numpy 2.5.4، scikit-learn 1.9.1، joblib 1.6.0، PySide6 6.12.0، pytest 9.2.0.",
         "- منصة Qt: `windows` (نافذة أصلية) بشاشة 1536×864؛ التفاعل عبر أحداث QTest على الودجات الحقيقية (وليس UI Automation على مستوى النظام)؛ اللقطات من `QWidget.grab()` للنافذة نفسها.",
         "- قواعد بيانات الاختبار مؤقتة ومعزولة تحت مجلد scratchpad؛ لم تُفتح قاعدة المستخدم `data/doctorcar.sqlite3` ولا يشير إليها أي سكربت QA.",
         "- أدوات غير متوفرة: ESP-IDF/CMake/Ninja/gcc، psutil، pywinauto/pyautogui.", "",
         "## 4. جرد الوظائف (Test Inventory)", "",
         f"عدد البنود الوظيفية المجرودة: **{len(inventory)}**؛ التصنيف: " + "، ".join(f"{k}: {v}" for k, v in inv_counts.items()) + ".",
         f"عدد الدوال/الأصناف العامة في كود المنتج (AST): **{sum(funcs.values())}** موزعة: " + "، ".join(f"{k} {v}" for k, v in sorted(funcs.items())) + ".",
         "تعريف التصنيف: **Verified** = كل الاختبارات المرتبطة PASS؛ **Partially Verified** = بعضها PASS/PARTIAL أو يوجد فشل جزئي؛ **Failed** = كلها FAIL؛ **Not Tested** = لا دليل؛ **Not Implemented** = الميزة غير موجودة في المنتج.", "",
         "| # | المجال | الوظيفة | الاختبارات | الحالة |", "| --- | --- | --- | --- | --- |"]
for n, it in enumerate(inventory, 1):
    lines.append(f"| {n} | {it['area']} | {it['function']} | {', '.join(it['tests']) or '—'} | **{it['status']}** |")
lines += ["", "جرد عناصر الواجهة الفعلية (من النافذة الحية): 10 أزرار، 1 CheckBox، 9 ComboBox، 3 قوائم، 5 SpinBox، 2 DoubleSpinBox، 2 جداول، 3 TextEdit، 11 LineEdit (منها حقول داخلية للـSpinBox)، 0 Slider، 0 قوائم شريطية، 0 اختصارات لوحة مفاتيح — `docs/evidence/full-qa/gate2/ui-inventory.json`.", "",
          "## 5. مصفوفة تتبع المتطلبات (RTM)", "", "| المتطلب | الاختبارات | PASS | FAIL | PARTIAL | NOT TESTED |", "| --- | --- | --- | --- | --- | --- |"]
for req in sorted(by_req):
    ids = sorted(set(by_req[req]))
    cnt = Counter(cases[i]["status"] for i in ids)
    lines.append(f"| {req} | {', '.join(ids[:8])}{'…' if len(ids) > 8 else ''} | {cnt['PASS']} | {cnt['FAIL']} | {cnt['PARTIAL']} | {cnt['NOT TESTED']} |")
lines += ["", "## 6. حالات الاختبار (المتوقع والفعلي والدليل)", "", f"الإجمالي: {len(cases)} حالة مسجلة — المسجَّل: " + "، ".join(f"{k}: {counts.get(k, 0)}" for k in ("PASS", "FAIL", "PARTIAL", "BLOCKED", "NOT TESTED")) + " — بعد التحكيم (فشلان سببهما سكربت QA، انظر adjudication.json): " + "، ".join(f"{k}: {adj_counts.get(k, 0)}" for k in ("PASS", "FAIL", "PARTIAL", "BLOCKED", "NOT TESTED")) + ".", "",
          "| ID | المتطلب | العنوان | المتوقع | الفعلي | الحالة | الدليل |", "| --- | --- | --- | --- | --- | --- | --- |"]
esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
for tid in sorted(cases):
    c = cases[tid]
    lines.append(f"| {tid} | {esc(c['requirement'])} | {esc(c['title'])[:110]} | {esc(c['expected'])[:150]} | {esc(c['actual'])[:200]} | **{c['status']}** | {esc(c['evidence'])} |")
lines += ["", "## 7. العيوب", "", f"عدد العيوب المسجلة: **{len(DEFECTS)}** — التفاصيل في `DEFECT_REGISTER.md`.", ""]
sev = Counter(d["severity"] for d in DEFECTS)
lines.append("، ".join(f"{k}: {sev.get(k, 0)}" for k in ("CRITICAL", "HIGH", "MEDIUM", "LOW")))
lines += ["", "## 8. المخاطر", "",
          "- نتائج الأداء كلها من مولد اصطناعي واحد: لا تثبت أداءً على مركبات.", "- الاختبار البصري آلي عبر QTest ولقطات؛ لا فحص بشري لكل دقة/DPI.", "- Firmware لم يُبنَ ولم يُشغَّل؛ كل ما سبق عنه مراجعة ساكنة.", "- قاعدة المستخدم لم تُفحص ولا تُمس.", "",
          "## 9. التغطية", "",
          f"- تغطية وظيفية: {inv_counts.get('Verified', 0)} Verified / {inv_counts.get('Partially Verified', 0)} Partial / {inv_counts.get('Failed', 0)} Failed / {inv_counts.get('Not Tested', 0)} Not Tested / {inv_counts.get('Not Implemented', 0)} Not Implemented من {len(inventory)} بندًا.",
          "- لم تُقَس تغطية الأسطر (أداة coverage غير مثبتة ولم أعدّل البيئة)؛ التغطية المذكورة وظيفية لا سطرية.", "",
          "## 10. معايير الخروج", "", "| المعيار | الحالة |", "| --- | --- |"]
exit_rows = [
    ("الواجهة الأساسية تعمل", "PASS" if status_of([f"QA-UI-0{i:02d}" for i in (2, 3, 5, 6, 10, 11)]) == "Verified" else "PARTIAL"),
    ("قراءات المحاكاة صحيحة وفق النموذج المعلن", "PASS" if status_of(["QA-SENSOR-003", "QA-SENSOR-005", "QA-SENSOR-006"]) == "Verified" else "PARTIAL"),
    ("الأعطال المحقونة تؤثر كما هو متوقع", "PASS" if status_of([f"QA-SIM-01{i}" for i in range(1, 8)] + ["QA-SIM-030"]) == "Verified" else "PARTIAL"),
    ("اكتشاف أحداث مبررة", "PARTIAL (القواعد قوية؛ تغطية ناقصة في ظروف محددة)"),
    ("التسجيل دون فقد غير مبرر", "PASS" if status_of([f"QA-EVENT-0{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14)]) == "Verified" else "PARTIAL"),
    ("ML يعمل وحدود دقته معروفة", "PARTIAL (يعمل؛ لا قيمة مضافة مثبتة وإنذارات كاذبة متبقية)"),
    ("XAI يفسر النموذج فعليًا", "PASS" if status_of(["QA-XAI-001", "QA-XAI-002", "QA-XAI-003", "QA-XAI-004"]) == "Verified" else "PARTIAL"),
    ("التقرير لا يعطي تشخيصًا قطعيًا", "PASS" if status_of([f"QA-DIAG-S0{i}" for i in range(1, 8)]) == "Verified" else "PARTIAL"),
    ("البيانات محفوظة ومستعادة", "PASS" if status_of(["QA-DB-002", "QA-DB-003", "QA-DB-006", "QA-E2E-008"]) == "Verified" else "PARTIAL"),
    ("التكامل الشبكي التجريبي", "PASS" if status_of(["QA-E2E-006", "QA-E2E-007", "QA-E2E-010"]) == "Verified" else "PARTIAL"),
    ("لا أخطاء حرجة غير معالجة في مسار العرض", "PASS (لا CRITICAL مسجل)" if not sev.get("CRITICAL") else "FAIL"),
    ("كل وظيفة غير مختبرة معلنة", "PASS (مدرجة في الجرد)"),
]
lines += [f"| {a} | {b} |" for a, b in exit_rows]
(EVIDENCE / "QA_MASTER_PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf8")

# ---------------------------------------------------------------------------- defect register
d = ["# DoctorCAR — Defect Register (DC-QA-001)", "", "لم يُصلَح أي عيب خلال الحملة. الحالة OPEN لكل العيوب. الخطورة: CRITICAL فقد بيانات/فساد/سلامة؛ HIGH خلل رئيسي في التشخيص أو AI أو التكامل؛ MEDIUM وظيفة جزئية أو سلوك غير صحيح مع بديل؛ LOW عيب بصري أو تحسين محدود.", ""]
order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
for x in sorted(DEFECTS, key=lambda z: (order[z["severity"]], z["id"])):
    d += [f"## {x['id']} — {x['title']}", "", f"- **الخطورة:** {x['severity']}", f"- **الفئة:** {x['category']}", f"- **المتطلب المتأثر:** {x['requirement']}", f"- **خطوات إعادة الإنتاج:** {x['steps']}",
          f"- **المتوقع:** {x['expected']}", f"- **الفعلي:** {x['actual']}", f"- **الدليل:** {x['evidence']}", f"- **السبب الجذري (مثبت/مشتبه):** {x['cause']}", f"- **الأثر على DoctorCAR:** {x['impact']}",
          f"- **الملفات المتأثرة:** {x['files']}", f"- **الإصلاح المقترح:** {x['fix']}", f"- **اختبار Regression المطلوب:** {x['regression']}", f"- **هل يمنع اعتماد النموذج الأولي؟** {x['blocks_prototype']}", f"- **الحالة:** {x.get('status', 'OPEN')}", ""]
d += ["---", "", "# أخطاء سكربتات QA نفسها (ليست عيوب منتج)", "",
      "لم تُعدَّل أي ملفات `results.json`. الفشلان المسجلان التاليان سببهما سكربت QA، وتصنيفهما النهائي في `adjudication.json` مع الدليل:", ""]
for tid, a_ in adj.items():
    d += [f"## {tid} — مسجَّل {a_['recorded']} ← مُحكَّم {a_['adjudicated_status']}", "", f"- **النوع:** {a_['cause_type']}", f"- **السبب:** {a_['reason']}", f"- **الدليل:** {a_['evidence']}", f"- **ما تحقق فعلًا:** {a_['verified_part']}", f"- **ما لم يتحقق:** {a_['not_verified']}", ""]
d += ["## سجل تصحيحات سكربتات QA أثناء الحملة", "", "حالات أخفقت أو نجحت نجاحًا غير صالح بسبب السكربت، ثم صُحح السكربت (ولم يُمس المنتج):", "", "| الاختبار | الحالة الأولى | السبب | السكربت المصحَّح |", "| --- | --- | --- | --- |"]
d += [f"| {c['test']} | {c['was']} | {c['cause']} | {c['fixed_in']} |" for c in ADJ.get("qa_script_corrections_log", [])]
d += ["", "# قيود البيئة (غير مختبر لهذا السبب)", ""] + [f"- {x}" for x in ADJ.get("environment_limits", [])] + [""]
(EVIDENCE / "DEFECT_REGISTER.md").write_text("\n".join(d) + "\n", encoding="utf8")
print("tests:", len(cases), dict(counts), "| inventory:", len(inventory), dict(inv_counts), "| defects:", len(DEFECTS))
