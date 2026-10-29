"""Explicitly scoped experimental rules. No mechanical diagnosis in this layer."""

from collections import deque

from doctorcar.core.models import Quality, Sample, Trigger
from doctorcar.core.simulation_profile import PROFILE
from doctorcar.monitoring.evidence_rules import (
    RULE_VERSION_MS,
    RULES,
    WINDOW_MS,
    evaluate_relations,
)

RULE_VERSION = "demo-rules-1.0"


class EventDetector:
    def __init__(self) -> None:
        self.hot_since: int | None = None
        self.thermal_latched = False
        self.quality_latched = False
        self.relation_window: deque[Sample] = deque(maxlen=512)
        self.relation_latches: set[str] = set()

    def evaluate_trigger(self, sample: Sample, issues: tuple[str, ...]) -> tuple[Trigger, ...]:
        triggers: list[Trigger] = []
        coolant, rpm = sample.readings.get("COOLANT_TEMP"), sample.readings.get("RPM")
        demo_context = sample.source.value in (
            "SIMULATION",
            "DEVICE_TEST",
        ) or sample.provenance in ("SIMULATION", "DEVICE_TEST")
        hot = (
            demo_context
            and sample.provenance != PROFILE
            and coolant is not None
            and coolant.quality == Quality.AVAILABLE
            and coolant.value is not None
            and coolant.value >= 108
            and rpm is not None
            and rpm.value is not None
            and rpm.value > 400
            and rpm.quality == Quality.AVAILABLE
        )
        if hot:
            if self.hot_since is None:
                self.hot_since = sample.timestamp_ms
            if sample.timestamp_ms - self.hot_since >= 3000 and not self.thermal_latched:
                self.thermal_latched = True
                triggers.append(
                    Trigger(
                        "THERMAL_DEMO",
                        "ارتفاع حراري غير معتاد ضمن السيناريو التجريبي",
                        "تجاوز \u2066108 °C\u2069 لمدة 3 ثوانٍ "
                        "مع دوران المحرك في نموذج الاختبار فقط",
                        RULE_VERSION,
                        sample.timestamp_ms,
                        (
                            f"COOLANT_TEMP={coolant.value if coolant else None} °C",
                            "demo_context=true",
                        ),
                    )
                )
        else:
            self.hot_since = None
            self.thermal_latched = False
        if issues and not self.quality_latched:
            triggers.append(
                Trigger(
                    "DATA_QUALITY",
                    "قراءة ناقصة أو غير صالحة أو فجوة في البيانات",
                    "إخفاق تحقق جودة البيانات؛ لا يثبت تلف حساس أو عطل كهربائي",
                    RULE_VERSION,
                    sample.timestamp_ms,
                    issues,
                )
            )
        self.quality_latched = bool(issues)
        if self.relation_window and self.relation_window[-1].session_id != sample.session_id:
            self.relation_window.clear()
            self.relation_latches.clear()
        self.relation_window.append(sample)
        while (
            self.relation_window
            and sample.timestamp_ms - self.relation_window[0].timestamp_ms > WINDOW_MS
        ):
            self.relation_window.popleft()
        findings = evaluate_relations(tuple(self.relation_window))
        for finding in findings:
            if finding.rule_id not in self.relation_latches:
                rule = RULES[finding.rule_id]
                triggers.append(
                    Trigger(
                        rule.rule_id,
                        rule.pattern_ar,
                        (
                            "علاقات متعددة القياسات ضمن معايرة نموذج محاكاة "
                            "معلن؛ لا تثبت سببًا ميكانيكيًا"
                        ),
                        RULE_VERSION_MS,
                        sample.timestamp_ms,
                        finding.supporting_evidence,
                    )
                )
        self.relation_latches = {f.rule_id for f in findings}
        return tuple(triggers)
