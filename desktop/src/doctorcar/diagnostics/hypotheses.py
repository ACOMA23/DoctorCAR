"""Small tested hypothesis interface; no invented 68-case catalogue."""

from dataclasses import dataclass

from doctorcar.core.models import Event
from doctorcar.diagnostics.evidence import Evidence
from doctorcar.monitoring.evidence_rules import RULES


@dataclass(frozen=True)
class Hypothesis:
    description: str
    supporting_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    recommended_check: str
    contradicting_evidence: tuple[str, ...] = ()
    description_en: str = ""
    missing_evidence_en: tuple[str, ...] = ()
    recommended_check_en: str = ""


def evaluate_hypotheses(event: Event, evidence: Evidence) -> tuple[Hypothesis, ...]:
    findings = [
        f
        for f in evidence.findings
        if f.rule_id == event.trigger.kind or event.trigger.kind == "ML_ANOMALY"
    ]
    if findings:
        result = []
        for finding in findings:
            rule = RULES[finding.rule_id]
            for index, cause in enumerate(rule.causes):
                result.append(
                    Hypothesis(
                        cause[0],
                        finding.supporting_evidence,
                        tuple(m[0] for m in rule.missing),
                        "؛ ".join(c[0] for c in rule.checks),
                        finding.contradicting_evidence if index else (),
                        cause[1],
                        tuple(m[1] for m in rule.missing),
                        "; ".join(c[1] for c in rule.checks),
                    )
                )
        return tuple(result)
    if event.trigger.kind == "THERMAL_DEMO" and evidence.maximum_temperature is not None:
        return (
            Hypothesis(
                "حالة حرارية مرتفعة في نموذج الاختبار؛ كفاءة التبريد احتمال يحتاج تحققًا",
                (f"أعلى قراءة صالحة: \u2066{evidence.maximum_temperature:.1f} °C\u2069",),
                ("مواصفات المركبة وظروف الحمل وقياس مستقل للحرارة غير متاحة",),
                "قارن بقياس حرارة مستقل ومواصفات المركبة قبل فحص منظومة التبريد",
            ),
            Hypothesis(
                "انحراف قياس أو مشكلة جودة بيانات احتمال بديل",
                ("القراءات ليست إثباتًا سببيًا",),
                ("لا يوجد تحقق مستقل من القياس",),
                "راجع مصدر القراءة ووحدتها وتوقيتها، ولا تستبدل قطعة بناءً على هذا التقرير",
            ),
        )
    if event.trigger.kind == "CONNECTION":
        return (
            Hypothesis(
                "انقطاع في مسار نقل البيانات",
                (event.trigger.reason,),
                ("سبب الانقطاع الفعلي غير مثبت",),
                "تحقق من المنفذ والكابل وحالة الجهاز؛ لا تستنتج عطل كهرباء المركبة",
            ),
        )
    return (
        Hypothesis(
            "الأدلة غير كافية لتحديد سبب ميكانيكي",
            tuple(event.trigger.evidence),
            ("قياسات موثوقة وسياق تشغيل كافٍ",),
            "تحقق من جودة القراءة ومصدرها قبل أي فحص ميكانيكي",
        ),
    )
