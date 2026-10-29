"""Versioned report data; rendering never runs inference or changes historical events."""

# Complete bilingual display phrases are retained together, as in ui/localization.py.
# ruff: noqa: E501

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

from doctorcar.analysis import status as ai
from doctorcar.core.models import Event, Trigger
from doctorcar.core.sensor_registry import REGISTRY
from doctorcar.diagnostics.evidence import build_evidence
from doctorcar.diagnostics.hypotheses import evaluate_hypotheses
from doctorcar.diagnostics.reports import build_diagnostic_report
from doctorcar.monitoring.evidence_rules import RULES, valid_value

NAMES = {
    "RPM": "Engine speed",
    "SPEED": "Vehicle speed",
    "COOLANT_TEMP": "Coolant temperature",
    "ENGINE_LOAD": "Engine load",
    "THROTTLE_POS": "Throttle position",
    "INTAKE_PRESSURE": "Intake pressure",
    "MAF": "Air flow",
    "INTAKE_TEMP": "Intake temperature",
    "SHORT_FUEL_TRIM": "Short fuel correction",
    "LONG_FUEL_TRIM": "Long fuel correction",
    "CONTROL_MODULE_VOLTAGE": "Module voltage",
}
RELATION_PHRASES = {
    "MAF.relative_residual": (
        "انحراف تدفق الهواء المقاس عن المتوقع",
        "Measured vs expected air flow",
    ),
    "INTAKE_PRESSURE.residual": ("انحراف ضغط السحب عن المتوقع", "Intake pressure vs expected"),
    "RPM.trim_correlation": (
        "ارتباط دوران المحرك بتصحيح الوقود",
        "Engine speed vs fuel correction link",
    ),
}
STAT_PHRASES = {
    "mean": ("متوسط", "Average"),
    "std": ("تذبذب", "Variability of"),
    "slope": ("اتجاه تغير", "Trend of"),
    "coverage": ("اكتمال قياسات", "Data completeness of"),
}
GROUP_NAMES = {
    "temperature": ("تغير الحرارة", "Temperature behavior"),
    "air_fuel_operation": (
        "علاقات الهواء والوقود وظروف التشغيل",
        "Air/fuel and operating relationships",
    ),
    "voltage": ("جهد التغذية", "Supply voltage"),
    "speed": ("سرعة المركبة", "Vehicle speed"),
}
Tr = Callable[[str, str], str]
NON_AI_KINDS = ("ML_ANOMALY", "DATA_QUALITY", "CONNECTION")


@dataclass(frozen=True)
class DiagnosticReport:
    report_version: str
    report_id: str
    event_id: str
    observation: dict[str, str]
    key_measurements: tuple[dict[str, Any], ...]
    hypotheses: tuple[dict[str, Any], ...]
    source: tuple[str, ...]
    origin: str
    recording_status: str
    detection_ms: int
    sample_count: int
    missing_count: int
    dtcs: tuple[str, ...]
    dtc_available: bool
    freeze_frame: bool
    technical: dict[str, str]
    analysis: dict[str, Any] | None
    detection_sources: tuple[dict[str, Any], ...] = ()
    hypothesis_evidence_ms: int | None = None
    ai_status: dict[str, Any] | None = None
    analysis_later: dict[str, Any] | None = None
    detection_summary: dict[str, Any] | None = None
    recording_window: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_ai_context(
    repository: Any, event: Event
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Return (analysis known at detection, AI status record, later anomalous analysis)."""
    status = repository.get_event_ai_status(event.event_id)
    detection = event.trigger.timestamp_ms
    if status is None:
        # Events saved before AI status existed keep their original linkage.
        return repository.get_event_analysis(event.event_id), None, None
    at_detection = None
    if status.get("state") in (ai.ANALYZED_NORMAL, ai.ANALYZED_ANOMALOUS):
        at_detection = repository.get_analysis(event.session_id, status["window_end_ms"])
        # Never present an analysis produced by a different model than the one recorded.
        if at_detection is not None and at_detection.get("model_sha256") != status.get(
            "model_sha256"
        ):
            at_detection = None
    later = next(
        (
            a
            for a in repository.get_event_analyses(event.event_id)
            if a["end_ms"] > detection and a.get("decision") == "ANOMALOUS"
        ),
        None,
    )
    return at_detection, status, later


def summarize_detection(event: Event, detections: list[dict[str, Any]] | None) -> dict[str, Any]:
    found = {event.trigger.kind: event.trigger.timestamp_ms}
    for d in detections or []:
        found.setdefault(d["kind"], d["timestamp_ms"])
    rules = {k: t for k, t in found.items() if k not in NON_AI_KINDS}
    return {
        "rule_kinds": sorted(rules),
        "rule_first_ms": min(rules.values()) if rules else None,
        "ml": "ML_ANOMALY" in found,
        "ml_ms": found.get("ML_ANOMALY"),
        "quality": "DATA_QUALITY" in found,
        "connection": "CONNECTION" in found,
        "combined": "ML_ANOMALY" in found and bool(rules),
    }


def build_report_model(
    event: Event,
    analysis: dict[str, Any] | None = None,
    detections: list[dict[str, Any]] | None = None,
    ai_status: dict[str, Any] | None = None,
    analysis_later: dict[str, Any] | None = None,
) -> DiagnosticReport:
    evidence = build_evidence(event)
    rule = RULES.get(event.trigger.kind)
    hypothesis_event = event
    # A rule may support an earlier ML event later. Keep its evidence time explicit;
    # never rewrite the ML feature vector or pretend those later facts were known at T.
    if event.trigger.kind == "ML_ANOMALY":
        additional = [d for d in detections or [] if d["kind"] in RULES]
        if additional:
            detail = min(additional, key=lambda d: d["timestamp_ms"])
            rule = RULES[detail["kind"]]
            hypothesis_event = replace(
                event, trigger=Trigger(**{**detail, "evidence": tuple(detail.get("evidence", ()))})
            )
    hypothesis_evidence = build_evidence(hypothesis_event)
    thermal = event.trigger.kind in ("MS_THERMAL", "THERMAL_DEMO") or bool(
        rule and rule.rule_id == "MS_THERMAL"
    )
    titles = {
        "ar": rule.pattern_ar
        if rule
        else ("ارتفاع غير طبيعي في حرارة المحرك" if thermal else "تغير يحتاج مراجعة في القياسات"),
        "en": rule.pattern_en
        if rule
        else ("Unusual engine temperature rise" if thermal else "Measurements need review"),
    }
    sensors = (
        ("COOLANT_TEMP", "SPEED", "ENGINE_LOAD")
        if thermal
        else ("CONTROL_MODULE_VOLTAGE", "RPM", "MAF")
        if event.trigger.kind == "MS_SUPPLY"
        else ("MAF", "INTAKE_PRESSURE", "SHORT_FUEL_TRIM")
    )
    before = [s for s in event.samples if s.timestamp_ms <= event.trigger.timestamp_ms]
    at = before[-1] if before else None
    measures = []
    for sensor in sensors:
        stats = evidence.measurements.get(sensor)
        if stats:
            measures.append(
                {
                    "sensor": sensor,
                    "unit": stats.unit,
                    "at_detection": valid_value(at, sensor) if at else None,
                    "maximum_recorded": stats.maximum,
                    "last_recorded": valid_value(event.samples[-1], sensor),
                    "last_ms": event.samples[-1].timestamp_ms,
                }
            )
    version = "human-report-2" if ai_status is not None else "human-report-1"
    return DiagnosticReport(
        version,
        f"{version}:{event.event_id}",
        event.event_id,
        titles,
        tuple(measures),
        tuple(asdict(h) for h in evaluate_hypotheses(hypothesis_event, hypothesis_evidence)),
        evidence.sources,
        event.origin,
        event.status,
        event.trigger.timestamp_ms,
        evidence.sample_count,
        evidence.invalid_reading_count,
        evidence.dtcs,
        evidence.dtc_available,
        evidence.has_freeze_frame,
        {lang: build_diagnostic_report(event, lang) for lang in ("ar", "en")},
        analysis,
        tuple(detections or ()),
        hypothesis_event.trigger.timestamp_ms,
        ai_status,
        analysis_later,
        summarize_detection(event, detections),
        {"first_ms": event.samples[0].timestamp_ms, "last_ms": event.samples[-1].timestamp_ms},
    )


def feature_phrase(name: str, language: str) -> str:
    index = 0 if language == "ar" else 1
    if name in RELATION_PHRASES:
        return RELATION_PHRASES[name][index]
    sensor, stat = name.split(".")
    label = REGISTRY.get(sensor).arabic_name if language == "ar" else NAMES[sensor].lower()
    return f"{STAT_PHRASES[stat][index]} {label}"


def effective_state(report: DiagnosticReport) -> str:
    if report.ai_status is not None:
        return str(report.ai_status["state"])
    if report.analysis is not None:
        return (
            ai.ANALYZED_ANOMALOUS
            if report.analysis.get("decision") == "ANOMALOUS"
            else ai.ANALYZED_NORMAL
        )
    return ai.HISTORICAL if report.origin == "HISTORICAL" else ai.NOT_RECORDED


def _sources_line(report: DiagnosticReport, tr: Tr) -> str | None:
    s = report.detection_summary
    if not s:
        return None
    state = effective_state(report)
    if s["combined"]:
        lag = (
            (s["rule_first_ms"] - s["ml_ms"]) / 1000
            if s["rule_first_ms"] is not None and s["ml_ms"] is not None
            else 0
        )
        return tr(
            "اكتشفه الذكاء الاصطناعي والقواعد معًا"
            + (f"؛ جاءت أدلة القواعد بعد الكشف الأول بنحو {lag:.1f} ثانية." if lag > 0 else "."),
            "Detected by both the AI and the rules"
            + (
                f"; rule evidence came about {lag:.1f} seconds after the first detection."
                if lag > 0
                else "."
            ),
        )
    if s["ml"]:
        return tr(
            "اكتشفه الذكاء الاصطناعي وحده؛ لم تؤكده قاعدة محددة ضمن نافذة التسجيل.",
            "Detected by the AI alone; no specific rule confirmed it within the recording window.",
        )
    if s["rule_kinds"]:
        if state == ai.ANALYZED_NORMAL:
            return tr(
                "اكتشفته القواعد؛ وحلل الذكاء الاصطناعي البيانات ولم يكتشف شذوذًا.",
                "Detected by the rules; the AI analyzed the data and found no anomaly.",
            )
        return tr("اكتشفته القواعد.", "Detected by the rules.")
    if s["quality"]:
        return tr("أُطلق بسبب مشكلة في جودة البيانات.", "Triggered by a data-quality problem.")
    return None


def _xai_lines(analysis: dict[str, Any], tr: Tr, ar: bool) -> list[str]:
    xai = analysis.get("xai", {})
    if xai.get("status") != "AVAILABLE":
        return [
            tr("تعذر تفسير قرار النموذج لهذه الحالة.", "Explanation unavailable for this decision.")
        ]
    index = 0 if ar else 1
    groups = [e for e in xai["effects"] if e.get("used_by_model", True) and e["effect"] > 1e-8][:3]
    if not groups:
        return [
            tr(
                "لم يرفع أي عامل درجة الشذوذ بصورة واضحة؛ التفسير غير حاسم.",
                "No factor clearly raised the anomaly score; the explanation is inconclusive.",
            )
        ]
    lines = [
        tr(
            "العوامل الأكثر تأثيرًا في قرار النموذج: ",
            "Factors that most raised the model's anomaly score: ",
        )
        + ("، " if ar else ", ").join(GROUP_NAMES[e["group"]][index] for e in groups)
    ]
    top = next(
        (
            f
            for f in xai.get("feature_effects", [])
            if f["effect"] > 1e-8 and any(f["index"] in e["feature_indices"] for e in groups[:1])
        ),
        None,
    )
    if top is not None:
        side = (
            tr("أعلى", "above") if top["relation_to_reference"] == "above" else tr("أدنى", "below")
        )
        lines.append(
            tr(
                f"ساهم {feature_phrase(top['name'], 'ar')} ({side} من المعتاد في بيانات التدريب) "
                f"في رفع درجة الشذوذ التي حسبها النموذج.",
                f"{feature_phrase(top['name'], 'en')} ({side} the training norm) contributed to "
                "raising the anomaly score the model computed.",
            )
        )
    lines.append(
        tr(
            "هذه تأثيرات على قرار النموذج، وليست أسبابًا ميكانيكية. "
            "الميزات مترابطة واستبدالها بمرجع قد لا يمثل تشغيلًا واقعيًا.",
            "These are model effects, not mechanical causes. Correlated features and reference replacement may not represent realistic operation.",
        )
    )
    return lines


def _ai_lines(report: DiagnosticReport, tr: Tr, ar: bool) -> list[str]:
    state = effective_state(report)
    language = "ar" if ar else "en"
    lines = [tr("ماذا لاحظ الذكاء الاصطناعي؟", "What did AI observe?")]
    if state == ai.NOT_RECORDED:
        lines.append(
            tr(
                "لم يُحلل هذا الحدث باستخدام الذكاء الاصطناعي؛ لا يوجد سجل لسبب ذلك (حدث أقدم من تسجيل حالة التحليل).",
                "This event has not been analyzed by AI; no reason was recorded (it predates AI status recording).",
            )
        )
        return lines
    lines.append(ai.message(state, language))
    a = report.analysis
    if state in (ai.ANALYZED_NORMAL, ai.ANALYZED_ANOMALOUS) and a is not None:
        age = report.ai_status.get("age_ms") if report.ai_status else None
        timing = (
            tr(" وانتهت عند لحظة الكشف.", " It ended at the moment of detection.")
            if age == 0
            else tr(
                f" وانتهت قبل لحظة الكشف بنحو {age / 1000:.1f} ثانية.",
                f" It ended about {age / 1000:.1f} seconds before detection.",
            )
            if age is not None
            else ""
        )
        lines.append(
            tr(
                f"حلل النظام قياسات الفترة {a['start_ms'] / 1000:.1f} إلى {a['end_ms'] / 1000:.1f} ثانية."
                + timing
                + " درجته ليست احتمال تلف قطعة؛ وقد تختلف عن القواعد.",
                f"Analyzed {a['start_ms'] / 1000:.1f} to {a['end_ms'] / 1000:.1f} seconds."
                + timing
                + " Its score is not a component failure probability and may disagree with rules.",
            )
        )
        if a["end_ms"] > report.detection_ms:
            lines.append(
                tr(
                    "هذا تحليل لاحق للكشف الأول؛ لا يفسر ما كان معروفًا لحظته.",
                    "This analysis followed initial detection; it does not describe knowledge at that earlier time.",
                )
            )
        if a.get("decision") == "ANOMALOUS":
            lines.extend(_xai_lines(a, tr, ar))
        else:
            lines.append(
                tr(
                    "لا توجد عوامل شذوذ لتفسيرها لأن النموذج لم يعدّ هذه الفترة غير معتادة.",
                    "There are no anomaly factors to explain because the model did not rate this period unusual.",
                )
            )
    elif (
        report.ai_status
        and report.ai_status.get("reason")
        and state
        in (
            ai.MODEL_NOT_LOADED,
            ai.INFERENCE_FAILED,
        )
    ):
        lines.append(tr("السبب التقني: ", "Technical reason: ") + str(report.ai_status["reason"]))
    later = report.analysis_later
    if later is not None:
        lines.append(
            tr(
                f"بعد الكشف الأول اكتشف الذكاء الاصطناعي نمطًا غير معتاد في الفترة المنتهية عند {later['end_ms'] / 1000:.1f} ثانية. هذا تحليل لاحق ولا يصف ما كان معروفًا لحظة الكشف.",
                f"After the first detection the AI detected an unusual pattern in the window ending at {later['end_ms'] / 1000:.1f} seconds. This is a later analysis and does not describe what was known at detection.",
            )
        )
        if later.get("decision") == "ANOMALOUS":
            lines.extend(_xai_lines(later, tr, ar))
    return lines


def render_simple(report: DiagnosticReport, language: str = "ar") -> str:
    ar = language == "ar"

    def tr(a: str, e: str) -> str:
        return a if ar else e

    def number(v: float | None) -> str:
        return tr("غير متاح", "Unavailable") if v is None else f"{v:.1f}"

    lines = [
        "DoctorCAR — " + report.observation[language],
        "",
        tr("ماذا حدث؟", "What happened?"),
        tr(
            f"رصد النظام تغيرًا عند {report.detection_ms / 1000:.1f} ثانية من بدء التسجيل. "
            "القراءات التالية تفرق بين لحظة الكشف وما سُجل بعدها؛ لا تثبت وحدها سبب التغير.",
            f"A change was observed {report.detection_ms / 1000:.1f} seconds into the session. "
            "Values below distinguish detection from later recording; they do not prove a cause.",
        ),
    ]
    sources = _sources_line(report, tr)
    if sources:
        lines.append(sources)
    lines.extend(["", tr("أهم القراءات", "Key measurements")])
    for m in report.key_measurements:
        name = REGISTRY.get(m["sensor"]).arabic_name if ar else NAMES[m["sensor"]]
        lines.append(
            tr(
                f"• {name}: عند الكشف {number(m['at_detection'])} {m['unit']}؛ "
                f"الأعلى خلال التسجيل {number(m['maximum_recorded'])}؛ "
                f"آخر قراءة {number(m['last_recorded'])} عند {m['last_ms'] / 1000:.1f} ثانية.",
                f"• {name}: at detection {number(m['at_detection'])} {m['unit']}; "
                f"recording peak {number(m['maximum_recorded'])}; "
                f"last {number(m['last_recorded'])} at {m['last_ms'] / 1000:.1f} seconds.",
            )
        )
    lines.extend(["", *_ai_lines(report, tr, ar)])
    lines.extend(["", tr("ما المشكلة المحتملة؟ وش ممكن يكون السبب؟", "Possible explanations")])
    if (
        report.hypothesis_evidence_ms is not None
        and report.hypothesis_evidence_ms > report.detection_ms
    ):
        lines.append(
            tr(
                f"تدعمت الفرضيات بأدلة القواعد عند {report.hypothesis_evidence_ms / 1000:.1f} ثانية بعد الكشف الأول. هذه الأدلة اللاحقة ليست مدخلات قرار AI السابق.",
                f"Rule evidence supporting these hypotheses arrived at {report.hypothesis_evidence_ms / 1000:.1f} seconds after initial detection. These later observations were not inputs to the earlier AI decision.",
            )
        )
    for h in report.hypotheses[:3]:
        description = h["description"] if ar else h["description_en"] or "Cause remains unconfirmed"
        lines.append(
            "• "
            + description
            + tr(
                " — احتمال مرتبط بالقياسات؛ يلزم فحص مستقل.",
                " — a measurement-based possibility requiring an independent check.",
            )
        )
    lines.extend(["", tr("وش أفحص؟", "What should be checked?")])
    checks = list(
        dict.fromkeys(
            h["recommended_check"]
            if ar
            else h["recommended_check_en"]
            or "Ask a technician to verify readings against an independent measurement."
            for h in report.hypotheses
        )
    )
    for i, check in enumerate(checks, 1):
        lines.append(
            f"{i}. {check}\n"
            + tr(
                "الهدف: التمييز بين تغير تشغيل حقيقي وانحراف القياس. "
                "الفحص الميكانيكي أو الكهربائي يحتاج فنيًا وأداة قياس مناسبة؛ لا تستبدل قطعة بهذا التقرير.",
                "Purpose: distinguish an operating change from measurement error. "
                "Mechanical or electrical work needs a technician and suitable equipment; "
                "do not replace a part based on this report.",
            )
        )
    lines.extend(
        [
            "",
            tr("هل النتيجة مؤكدة؟", "How certain is this?"),
            tr(
                "اشتباه يحتاج تأكيدًا. الأدلة غير كافية لتحديد السبب المحتمل بصورة قاطعة.",
                "Suspicion requiring confirmation. Evidence cannot establish the mechanical cause.",
            ),
            "",
            tr("حالة البيانات", "Data status"),
            tr(
                "محاكاة أو جهاز تجريبي؛ لا مصدر مركبة حقيقي متحقق.",
                "Simulation or test device; no verified real vehicle source.",
            ),
            tr(
                f"القراءات الناقصة/غير الصالحة: {report.missing_count}؛ العينات: {report.sample_count}.",
                f"Missing/invalid readings: {report.missing_count}; samples: {report.sample_count}.",
            ),
            tr("التسجيل: ", "Recording: ")
            + (
                {"COMPLETE": "مكتمل", "PARTIAL": "جزئي", "RECORDING": "قيد التسجيل"}.get(
                    report.recording_status, report.recording_status
                )
                if ar
                else report.recording_status
            ),
            tr("طريقة العرض: ", "Origin: ")
            + (
                {"LIVE": "مباشر", "REPLAY": "إعادة تشغيل", "HISTORICAL": "تاريخي"}.get(
                    report.origin, report.origin
                )
                if ar
                else report.origin
            ),
            "DTC: "
            + (
                ", ".join(report.dtcs) or tr("لا رمز مرصود", "No code observed")
                if report.dtc_available
                else tr("غير متاح", "Unavailable")
            ),
            "Freeze Frame: "
            + tr(
                "مرفق" if report.freeze_frame else "غير متاح",
                "Attached" if report.freeze_frame else "Unavailable",
            ),
            "",
            tr("ملاحظة السلامة", "Safety note"),
            tr(
                "هذه تجربة برمجية وليست بلاغ خطر من مركبة حقيقية.",
                "This is a software experiment, not a real vehicle danger alert.",
            ),
        ]
    )
    return "\n".join(lines)


def _technical_ai(report: DiagnosticReport, language: str) -> str:
    ar = language == "ar"
    out = ["", "=== " + ("تفاصيل الذكاء الاصطناعي" if ar else "AI details") + " ==="]
    status = report.ai_status or {}
    out.append(
        f"state: {effective_state(report)}"
        + (f" — {status['reason']}" if status.get("reason") else "")
    )
    for key in (
        "model_version",
        "model_sha256",
        "score",
        "threshold",
        "window_start_ms",
        "window_end_ms",
        "age_ms",
        "max_age_ms",
    ):
        if key in status:
            out.append(f"{key}: {status[key]}")
    out.append(f"detection_ms: {report.detection_ms}")
    if report.recording_window:
        out.append(
            f"recording_window_ms: {report.recording_window['first_ms']}..{report.recording_window['last_ms']}"
        )
    out.append(f"samples: {report.sample_count}; missing_or_invalid: {report.missing_count}")
    s = report.detection_summary or {}
    out.append(
        "detection: "
        f"rules={s.get('rule_kinds')} (first {s.get('rule_first_ms')}); "
        f"ml={s.get('ml')} (at {s.get('ml_ms')}); quality={s.get('quality')}; combined={s.get('combined')}"
    )
    for label, analysis in (("at detection", report.analysis), ("later", report.analysis_later)):
        xai = (analysis or {}).get("xai", {})
        if xai.get("status") == "AVAILABLE":
            out.append(
                f"XAI ({label}) {xai['method']}: score {xai['original_score']:.4f}, threshold {xai.get('threshold')}"
            )
            for e in xai["effects"]:
                note = "" if e.get("used_by_model", True) else " [not read by this model]"
                out.append(
                    f"  group {e['group']}: effect {e['effect']:+.5f} ({e.get('direction')}){note}"
                )
            for f in xai.get("feature_effects", [])[:5]:
                out.append(
                    f"  feature {f['name']}: value {f['value']:.4g} vs reference {f['reference']:.4g}, effect {f['effect']:+.5f}"
                )
            out.append("  " + xai["limitations"])
    return "\n".join(out)


def render_technical(report: DiagnosticReport, language: str = "ar") -> str:
    text = report.technical[language]
    if report.analysis is None and report.ai_status is None and report.analysis_later is None:
        return text
    # Keep legacy renderer intact for old reports, remove its obsolete no-ML statements here.
    text = text.replace("ولا ML/XAI", "").replace("or ML/XAI", "")
    text = text.replace(
        "لم يُستخدم نموذج ذكاء اصطناعي أو XAI في M1، ولم تُختبر مركبة فعلية.", "لم تُختبر مركبة فعلية."
    )
    text = text.replace("No AI/XAI or actual vehicle testing in M1.", "No actual vehicle testing.")
    return (
        text
        + _technical_ai(report, language)
        + "\n\n"
        + (
            "تحليل AI وXAI المحفوظ — التوقيت والميزات الأصلية\n"
            if language == "ar"
            else "Stored AI/XAI — original timing and features\n"
        )
        + json.dumps(report.analysis, ensure_ascii=False, indent=2)
        + "\nLater analysis (after detection):\n"
        + json.dumps(report.analysis_later, ensure_ascii=False, indent=2)
        + "\nDetection sources (each at its own timestamp):\n"
        + json.dumps(report.detection_sources, ensure_ascii=False, indent=2)
        + "\nMechanical hypotheses — evidence time explicitly separate from ML:\n"
        + json.dumps(
            {"evidence_time_ms": report.hypothesis_evidence_ms, "hypotheses": report.hypotheses},
            ensure_ascii=False,
            indent=2,
        )
    )
