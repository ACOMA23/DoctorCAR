"""Test ground truth only. Neither detector nor diagnostic inference imports this module."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, replace
from typing import Any

from doctorcar.core.models import Quality, Reading, Sample

SCHEDULE_VERSION = "fault-schedule-1"
MODES = ("NORMAL", "FAULT_INJECTION", "RANDOM_FAULTS")


@dataclass(frozen=True)
class FaultDefinition:
    fault_id: str
    arabic_name: str
    english_name: str
    description: str
    sensors: tuple[str, ...]
    behavior: str
    expected_evidence: str
    detected_by: tuple[str, ...]
    default_duration_ms: int = 5000
    default_start_ms: int = 60000
    default_severity: float = 1.0
    merge_rule: str = "Reject overlapping definitions that write the same sensor"

    @property
    def detectable_in_m1(self) -> bool:
        return bool(self.detected_by)


FAULTS = {
    f.fault_id: f
    for f in (
        FaultDefinition(
            "thermal_gradual",
            "ارتفاع حرارة تدريجي",
            "Gradual temperature rise",
            "إشارة حرارية تدريجية تجريبية؛ لا تحدد قطعة",
            ("COOLANT_TEMP",),
            "gradual",
            "ارتفاع حرارة صالح مع الزمن",
            ("THERMAL_DEMO",),
            20000,
        ),
        FaultDefinition(
            "thermal_sudden",
            "ارتفاع حرارة مفاجئ",
            "Sudden temperature rise",
            "قفزة حرارية قصيرة تعود بعدها القراءة الطبيعية",
            ("COOLANT_TEMP",),
            "sudden",
            "حرارة صالحة مرتفعة لمدة تكفي قاعدة M1 عند الشدة الافتراضية",
            ("THERMAL_DEMO",),
        ),
        FaultDefinition(
            "temperature_invalid",
            "حرارة غير منطقية",
            "Implausible temperature",
            "قيمة جودة بيانات مقصودة، لا إثبات تلف حساس",
            ("COOLANT_TEMP",),
            "sudden",
            "حرارة -999 خارج حدود المحاكاة",
            ("DATA_QUALITY",),
        ),
        FaultDefinition(
            "sensor_dropout",
            "انقطاع قراءة حساس",
            "Sensor reading dropout",
            "غياب قراءة الحرارة مع بقاء الاتصال والعينات الأخرى",
            ("COOLANT_TEMP",),
            "missing",
            "قيمة null وMISSING",
            ("DATA_QUALITY",),
        ),
        FaultDefinition(
            "maf_bias",
            "انحراف قراءة MAF",
            "MAF bias",
            "انحراف إشارة تدفق الهواء؛ لا تشخيص حساس",
            ("MAF",),
            "bias",
            "MAF أقل من النموذج الأساسي",
            (),
        ),
        FaultDefinition(
            "map_frozen",
            "قراءة MAP ثابتة",
            "Frozen MAP reading",
            "إشارة INTAKE_PRESSURE ثابتة ضمن نطاق معقول",
            ("INTAKE_PRESSURE",),
            "frozen",
            "ثبات MAP رغم تغير ظروف التشغيل؛ للعرض فقط",
            (),
        ),
        FaultDefinition(
            "low_voltage",
            "انخفاض جهد",
            "Low voltage",
            "قيمة جهد تجريبية منخفضة؛ لا قياس ADC أو تشخيص بطارية",
            ("CONTROL_MODULE_VOLTAGE",),
            "sudden",
            "انخفاض الجهد دون حدود عتادية عامة",
            (),
        ),
        FaultDefinition(
            "fuel_trim",
            "تصحيحات وقود غير اعتيادية",
            "Unusual fuel trims",
            "تصحيحات موجبة تجريبية دون تحديد سبب احتراق",
            ("SHORT_FUEL_TRIM", "LONG_FUEL_TRIM"),
            "bias",
            "تصحيحات وقود موجبة",
            (),
        ),
        FaultDefinition(
            "misfire_pattern",
            "نمط اختلال احتراق متقطع مشتبه",
            "Suspected intermittent misfire pattern",
            "نمط إشارات فقط؛ لا DTC أو إثبات كويل",
            ("RPM", "ENGINE_LOAD"),
            "intermittent",
            "نبضات RPM وحمل متقطعة دون رمز عطل مخترع",
            (),
            12000,
        ),
        FaultDefinition(
            "air_pattern",
            "نمط سحب هواء غير اعتيادي مشتبه",
            "Suspected unusual intake pattern",
            "نمط MAF/MAP/trim تجريبي لا يثبت تسريبًا",
            ("MAF", "INTAKE_PRESSURE", "SHORT_FUEL_TRIM"),
            "gradual",
            "تغيرات مترابطة في الهواء وتصحيح الوقود؛ للعرض فقط",
            (),
            20000,
        ),
    )
}


@dataclass(frozen=True)
class FaultInstance:
    fault_id: str
    start_ms: int = 60000
    duration_ms: int = 5000
    severity: float = 1.0

    def __post_init__(self) -> None:
        if self.fault_id not in FAULTS:
            raise ValueError("Unknown fault_id")
        if type(self.start_ms) is not int or self.start_ms < 0:
            raise ValueError("Fault start must be nonnegative integer milliseconds")
        if type(self.duration_ms) is not int or not 1 <= self.duration_ms <= 60000:
            raise ValueError("Fault duration must be 1..60000 ms")
        if isinstance(self.severity, bool) or not 0.1 <= self.severity <= 1.0:
            raise ValueError("Severity must be 0.1..1.0")

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms


def validate_schedule(schedule: tuple[FaultInstance, ...]) -> None:
    for index, first in enumerate(schedule):
        for second in schedule[index + 1 :]:
            overlap = max(first.start_ms, second.start_ms) < min(first.end_ms, second.end_ms)
            if overlap and set(FAULTS[first.fault_id].sensors) & set(
                FAULTS[second.fault_id].sensors
            ):
                raise ValueError(f"Conflicting faults: {first.fault_id}, {second.fault_id}")


def random_schedule(
    seed: int, duration_ms: int, max_faults: int = 3, normal_probability: float = 0.25
) -> tuple[tuple[FaultInstance, ...], list[dict[str, Any]]]:
    if type(max_faults) is not int or not 1 <= max_faults <= 3:
        raise ValueError("max_faults must be 1..3")
    if not 0 <= normal_probability <= 1:
        raise ValueError("normal_probability must be 0..1")
    rng = random.Random(seed ^ 0xDC002)
    schedule: list[FaultInstance] = []
    cycles: list[dict[str, Any]] = []
    for start in range(30000, duration_ms, 30000):
        selected: list[str] = []
        if rng.random() >= normal_probability:
            candidates = list(FAULTS)
            rng.shuffle(candidates)
            count = rng.randint(1, max_faults)
            for fault_id in candidates:
                if any(
                    set(FAULTS[fault_id].sensors) & set(FAULTS[old].sensors) for old in selected
                ):
                    continue
                selected.append(fault_id)
                duration = rng.choice((5000, 12000, 20000))
                schedule.append(FaultInstance(fault_id, start, duration, rng.choice((0.7, 1.0))))
                if len(selected) == count:
                    break
        cycles.append({"start_ms": start, "fault_ids": selected})
    result = tuple(schedule)
    validate_schedule(result)
    return result, cycles


def apply_faults(sample: Sample, schedule: tuple[FaultInstance, ...]) -> Sample:
    readings = dict(sample.readings)
    for instance in schedule:
        if not instance.start_ms <= sample.timestamp_ms < instance.end_ms:
            continue
        fault_id, severity = instance.fault_id, instance.severity
        elapsed = sample.timestamp_ms - instance.start_ms
        progress = min(1.0, elapsed / max(1, instance.duration_ms - 200))

        def change(sensor: str, value: float | None, quality: Quality = Quality.AVAILABLE) -> None:
            readings[sensor] = Reading(
                round(value, 3) if value is not None else None, readings[sensor].unit, quality
            )

        def value(sensor: str) -> float:
            return readings[sensor].value or 0.0

        if fault_id == "thermal_gradual":
            change("COOLANT_TEMP", min(165, value("COOLANT_TEMP") + 60 * severity * progress))
        elif fault_id == "thermal_sudden":
            change("COOLANT_TEMP", 110 + 25 * severity)
        elif fault_id == "temperature_invalid":
            change("COOLANT_TEMP", -999)
        elif fault_id == "sensor_dropout":
            change("COOLANT_TEMP", None, Quality.MISSING)
        elif fault_id == "maf_bias":
            change("MAF", value("MAF") * (1 - 0.5 * severity))
        elif fault_id == "map_frozen":
            change("INTAKE_PRESSURE", 45)
        elif fault_id == "low_voltage":
            change("CONTROL_MODULE_VOLTAGE", 13.9 - 5 * severity)
        elif fault_id == "fuel_trim":
            change("SHORT_FUEL_TRIM", value("SHORT_FUEL_TRIM") + 25 * severity)
            change("LONG_FUEL_TRIM", value("LONG_FUEL_TRIM") + 18 * severity)
        elif fault_id == "misfire_pattern" and (elapsed // 1000) % 2 == 0:
            change("RPM", max(0, value("RPM") * (1 - 0.25 * severity)))
            change("ENGINE_LOAD", min(100, value("ENGINE_LOAD") + 15 * severity))
        elif fault_id == "air_pattern":
            change("MAF", value("MAF") * (1 - 0.35 * severity * progress))
            change("INTAKE_PRESSURE", min(105, value("INTAKE_PRESSURE") + 20 * severity * progress))
            change("SHORT_FUEL_TRIM", value("SHORT_FUEL_TRIM") + 20 * severity * progress)
    return replace(sample, readings=readings)


def schedule_metadata(
    mode: str,
    seed: int,
    duration_ms: int,
    step_ms: int,
    schedule: tuple[FaultInstance, ...],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "seed": seed,
        "duration_ms": duration_ms,
        "step_ms": step_ms,
        "schedule_version": SCHEDULE_VERSION,
        "cycles": cycles,
        "fault_schedule": [asdict(f) for f in schedule],
    }
