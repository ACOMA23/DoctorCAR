from doctorcar.core.models import Event
from doctorcar.diagnostics.evidence import build_evidence
from doctorcar.diagnostics.hypotheses import evaluate_hypotheses
from doctorcar.monitoring.evidence_rules import RULES


def build_multisensor_report(event: Event, language: str) -> str:
    evidence = build_evidence(event)
    en = language == "en"

    def label(ar: str, english: str) -> str:
        return english if en else ar

    findings = [f for f in evidence.findings if f.rule_id == event.trigger.kind]
    rule = RULES.get(event.trigger.kind)
    hypotheses = evaluate_hypotheses(event, evidence)
    lines = [
        label("DoctorCAR — تقرير أدلة متعدد القياسات", "DoctorCAR — multisensor evidence report"),
        f"Event ID: {event.event_id}",
        f"Session: {event.session_id}",
        f"Source: {', '.join(evidence.sources)} | {event.origin}",
        f"Recording: {event.status} | Detection: {event.trigger.timestamp_ms} ms | "
        f"{event.trigger.rule_version}",
        label("A. الأعراض المرصودة", "A. Observed Symptoms"),
        (rule.pattern_en if en else rule.pattern_ar) if rule else event.trigger.observation,
        label("B. القياسات الفعلية في نافذة الحدث", "B. Measurements in the actual event window"),
    ]
    for sensor, stats in evidence.measurements.items():
        lines.append(
            f"{sensor} [{stats.unit}] n={stats.count} "
            f"t={stats.start_ms}..{stats.end_ms} ms | min={stats.minimum:.3f} "
            f"max={stats.maximum:.3f} mean={stats.mean:.3f} delta={stats.delta:.3f}"
        )
    lines.append(
        label(
            "C. أدلة العلاقات حتى لحظة الكشف فقط", "C. Cross-Sensor Evidence through detection only"
        )
    )
    if findings:
        for finding in findings:
            lines.extend(finding.supporting_evidence)
        if rule:
            lines.append(
                label("حدود القاعدة التجريبية: ", "Experimental rule criteria: ")
                + rule.numeric_conditions
            )
    else:
        lines.append(
            label(
                "لا توجد أدلة علاقات مؤهلة لهذا الحدث؛ ملاحظة الجودة ليست تشخيص سبب.",
                (
                    "No qualified relational evidence for this event; "
                    "quality is not a cause diagnosis."
                ),
            )
        )
    lines.extend(
        [
            label(
                "التصنيف المشتق، منفصل عن Quality:",
                "Derived classification, separate from Quality:",
            ),
            *[f"{sensor}: {state}" for sensor, state in evidence.sensor_states.items()],
            label("D. النظام المحتمل المتأثر", "D. Suspected System"),
            (rule.system_en if en else rule.system_ar)
            if rule and findings
            else label("غير محسوم", "Unresolved"),
            label(
                "E. الأسباب المحتملة — فرضيات قابلة للفحص",
                "E. Possible Causes — testable hypotheses",
            ),
        ]
    )
    seen_checks: dict[str, int] = {}
    for number, h in enumerate(hypotheses, 1):
        check = h.recommended_check_en if en and h.recommended_check_en else h.recommended_check
        first = seen_checks.setdefault(check, number)
        lines.extend(
            [
                h.description_en if en and h.description_en else h.description,
                label("F. الأدلة الداعمة:", "F. Supporting Evidence:"),
                *h.supporting_evidence,
                label("G. الأدلة المعارضة للفرضية:", "G. Contradicting Evidence:"),
                *(
                    h.contradicting_evidence
                    or (
                        label(
                            "لم يتوفر دليل معارض مستقل؛ هذا لا يؤكد الفرضية.",
                            (
                                "No independent contradiction available; this "
                                "does not confirm the hypothesis."
                            ),
                        ),
                    )
                ),
                label("H. البيانات الناقصة:", "H. Missing Evidence:"),
                *(h.missing_evidence_en if en and h.missing_evidence_en else h.missing_evidence),
                label("I. الفحوص المقترحة:", "I. Recommended Checks:"),
                check
                if first == number
                else label(
                    f"الفحص نفسه المذكور تحت الفرضية {first}.",
                    f"Same check as listed under hypothesis {first}.",
                ),
            ]
        )
    lines.extend(
        [
            label("J. الحدود", "J. Limitations"),
            label(
                "الأدلة غير كافية لتحديد السبب المحتمل.",
                "Evidence is insufficient to identify the probable cause.",
            ),
            label(
                (
                    "هذه علاقات تجريبية معايرة لنموذج محاكاة معلن؛ ليست "
                    "معايير عامة أو محاكاة فيزيائية دقيقة."
                ),
                (
                    "These rules are calibrated to a declared toy simulation, "
                    "not universal limits or validated physics."
                ),
            ),
            label(
                "النمط لا يثبت تلف قطعة أو Misfire أو أسطوانة؛ لا ثقة ميكانيكية معايرة ولا ML/XAI.",
                (
                    "A pattern proves no failed part, misfire or cylinder; no "
                    "calibrated mechanical confidence or ML/XAI."
                ),
            ),
            label(
                (
                    "جهد وحدة التحكم ليس تيار البطارية؛ لا Fuel Pressure "
                    "PID أو DTC أو Freeze Frame مخترع."
                ),
                (
                    "Module voltage is not battery current; no invented "
                    "fuel pressure PID, DTC or Freeze Frame."
                ),
            ),
            "DTC: "
            + (
                ", ".join(evidence.dtcs) or label("لا رمز مرصود", "No code observed")
                if evidence.dtc_available
                else label("غير متاح أو غير مدعوم", "Unavailable or unsupported")
            ),
            "Freeze Frame: "
            + (
                label("مرفق؛ راجع المصدر الأصلي", "Attached; inspect original source")
                if evidence.has_freeze_frame
                else label(
                    "غير متاح؛ النافذة ليست ECU Freeze Frame",
                    "Unavailable; this window is not ECU Freeze Frame",
                )
            ),
            *event.limitations,
            label("K. نافذة الحدث الفعلية", "K. Event Window"),
            f"T={event.trigger.timestamp_ms} ms | "
            f"requested={event.trigger.timestamp_ms - 30000}.."
            f"{event.trigger.timestamp_ms + 30000} ms",
            f"actual={evidence.start_ms}..{evidence.end_ms} ms | "
            f"n={evidence.sample_count} | {event.status}",
        ]
    )
    return "\n".join(lines)


def build_diagnostic_report(event: Event, language: str = "ar") -> str:
    evidence = build_evidence(event)
    if evidence.calibrated_model:
        return build_multisensor_report(event, language)
    if language == "en":
        return "\n".join(
            [
                "DoctorCAR — experimental event report",
                f"Event ID: {event.event_id}",
                f"Session: {event.session_id}",
                f"Source: {', '.join(evidence.sources)} | Origin: {event.origin}",
                f"Recording: {event.status} | Rule: {event.trigger.rule_version}",
                f"Detection: {event.trigger.timestamp_ms / 1000:.3f} seconds",
                f"Samples: {evidence.sample_count} | "
                f"Window: {evidence.start_ms}..{evidence.end_ms} ms",
                f"Maximum valid coolant temperature: {evidence.maximum_temperature} °C",
                f"Invalid/unavailable readings: {evidence.invalid_reading_count}",
                f"DTC: {', '.join(evidence.dtcs) if evidence.dtc_available else 'Unavailable'}",
                "Freeze Frame: "
                + (
                    "Attached; see original data"
                    if evidence.has_freeze_frame
                    else "Unavailable; this window is not ECU Freeze Frame"
                ),
                "Original stored diagnostic text (Arabic preserved):",
                event.trigger.observation,
                event.trigger.reason,
                *event.trigger.evidence,
                "Original report and alternative hypotheses (Arabic preserved):",
                build_diagnostic_report(event, "ar"),
                "Limitations: experimental rules; no calibrated mechanical confidence.",
                "An anomaly does not prove component damage or mechanical causation.",
                "No AI/XAI or actual vehicle testing in M1.",
            ]
        )
    hypotheses = evaluate_hypotheses(event, evidence)
    temperature = evidence.maximum_temperature
    temperature_text = (
        f"\u2066{temperature:.3f} °C\u2069" if temperature is not None else "غير متاحة"
    )
    status = {"COMPLETE": "مكتمل", "PARTIAL": "جزئي", "RECORDING": "قيد التسجيل"}[event.status]
    dtc_text = (
        ", ".join(evidence.dtcs) or "لا يوجد رمز مؤكد ضمن البيانات المتاحة"
        if evidence.dtc_available
        else "غير متاحة أو غير مدعومة"
    )
    lines = [
        "DoctorCAR — تقرير حدث تجريبي",
        f"معرف الحدث: {event.event_id}",
        f"المصدر: {', '.join(evidence.sources) or 'غير متاح'}",
        f"حالة التسجيل: {status}",
        "",
        "الملاحظة:",
        event.trigger.observation,
        "السلوك المكتشف:",
        event.trigger.reason,
        f"إصدار القاعدة: {event.trigger.rule_version}",
        f"لحظة الكشف: {event.trigger.timestamp_ms / 1000:.3f} ثانية من بدء جلسة المصدر",
        "الظروف والأدلة:",
        f"العينات: {evidence.sample_count}؛ النافذة الفعلية: "
        f"\u2066{evidence.start_ms}..{evidence.end_ms} ms\u2069",
        f"أعلى حرارة صالحة متاحة: {temperature_text}",
        f"القراءات غير المتاحة أو غير الصالحة: {evidence.invalid_reading_count}",
        f"DTC المرصودة: {dtc_text}",
        "Freeze Frame: "
        + (
            "يوجد إطار مرفق بمصدره؛ راجع بياناته الأصلية"
            if evidence.has_freeze_frame
            else "غير متاح؛ نافذة DoctorCAR ليست ECU Freeze Frame"
        ),
        *event.trigger.evidence,
        "",
        "الأسباب المحتملة والبدائل:",
    ]
    for h in hypotheses:
        lines.extend(
            [
                f"• {h.description}",
                f"الدليل: {'؛ '.join(h.supporting_evidence)}",
                f"البيانات الناقصة: {'؛ '.join(h.missing_evidence)}",
                f"الفحص الفاصل المقترح: {h.recommended_check}",
            ]
        )
    lines.extend(
        [
            "",
            "حدود النتيجة:",
            *event.limitations,
            "قواعد الحرارة هنا خاصة بسيناريو تجريبي، وليست معيارًا عامًا لجميع المركبات.",
            "كشف الشذوذ لا يثبت تلف قطعة أو السبب الجذري، ولا توجد نسبة ثقة ميكانيكية معايرة.",
            "لم يُستخدم نموذج ذكاء اصطناعي أو XAI في M1، ولم تُختبر مركبة فعلية.",
            "يلتقط المسجل العينات التي وصلت فقط؛ الفجوات ومعدل الإرسال يحدان من تفاصيل الحدث.",
        ]
    )
    return "\n".join(lines)
