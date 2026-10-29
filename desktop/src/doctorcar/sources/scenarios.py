"""Correlated synthetic scenarios and ground truth; never imported by inference."""

import math
import random
from dataclasses import asdict, dataclass, replace
from typing import Any

from doctorcar.core.models import Quality, Reading, Sample
from doctorcar.core.simulation_profile import PROFILE, expected_maf, expected_map

SCENARIO_VERSION = "correlated-schedule-1"


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    arabic_name: str
    english_name: str
    system: str
    operating_conditions: str
    sensors: tuple[str, ...]
    writes: tuple[str, ...]
    relationships: str
    evolution: str
    expected_evidence: str
    alternative_hypotheses: tuple[str, ...]
    recommended_checks: tuple[str, ...]
    default_start_ms: int = 60000
    default_duration_ms: int = 35000
    default_severity: float = 1.0
    recovery: str = "Return to the underlying trip at the end; no synthetic history rewrite"


SCENARIOS_MS = {
    s.scenario_id: s
    for s in (
        ScenarioDefinition(
            "S01",
            "نمط اضطراب التبريد",
            "Thermal system pattern",
            "Cooling",
            "Engine running; heating follows load/RPM and airflow from vehicle speed",
            ("COOLANT_TEMP", "RPM", "SPEED", "ENGINE_LOAD", "THROTTLE_POS", "INTAKE_TEMP"),
            ("COOLANT_TEMP", "INTAKE_TEMP"),
            "Exponential heat accumulation, scaled by load/RPM/throttle and reduced by speed",
            "gradual",
            "High temperature with sustained rise under measured load",
            ("Reduced cooling effectiveness", "Temperature measurement bias"),
            ("Coolant level", "Fan operation", "Cooling circulation", "Independent temperature"),
        ),
        ScenarioDefinition(
            "S02",
            "نمط عدم توافق الهواء والوقود",
            "Suspected intake air leak",
            "Air/fuel",
            "Running engine; stronger effect at lower throttle",
            (
                "MAF",
                "INTAKE_PRESSURE",
                "RPM",
                "ENGINE_LOAD",
                "SHORT_FUEL_TRIM",
                "LONG_FUEL_TRIM",
                "THROTTLE_POS",
            ),
            ("MAF", "INTAKE_PRESSURE", "RPM", "ENGINE_LOAD", "SHORT_FUEL_TRIM", "LONG_FUEL_TRIM"),
            "Unmetered-air proxy raises MAP/trims while measured MAF is below contextual baseline",
            "load dependent",
            "Positive trims plus MAF/MAP disagreement",
            ("Intake leakage", "Air measurement bias", "Fuel delivery limitation"),
            ("Suitable leak test", "Intake hoses", "Compare MAF/MAP and trims across loads"),
        ),
        ScenarioDefinition(
            "S03",
            "نمط قصور استجابة إمداد الوقود",
            "Suspected fuel delivery pattern",
            "Air/fuel",
            "Running engine; stronger trim response under load",
            ("SHORT_FUEL_TRIM", "LONG_FUEL_TRIM", "MAF", "INTAKE_PRESSURE", "RPM", "ENGINE_LOAD"),
            ("SHORT_FUEL_TRIM", "LONG_FUEL_TRIM", "MAF", "INTAKE_PRESSURE", "RPM", "ENGINE_LOAD"),
            "Demand-linked trims with modest RPM response, near-consistent airflow references",
            "load dependent",
            "Positive trims under load with relatively consistent air references",
            ("Limited fuel supply", "Air leak", "Measurement bias"),
            (
                "External fuel pressure measurement with suitable equipment",
                "Fuel supply inspection",
            ),
        ),
        ScenarioDefinition(
            "S04",
            "نمط عدم اتساق قياس الهواء",
            "Airflow measurement inconsistency",
            "Air measurement",
            "Running engine; bias changes with load and elapsed time",
            ("MAF", "INTAKE_PRESSURE", "RPM", "THROTTLE_POS", "ENGINE_LOAD", "INTAKE_TEMP"),
            ("MAF", "INTAKE_TEMP"),
            "MAF bias and small temperature-channel bias; MAP/load/RPM remain reference signals",
            "drift",
            "MAF deviates while MAP is consistent; trims need not be high",
            ("MAF measurement bias", "Actual airflow change", "Wiring or reference-model mismatch"),
            (
                "MAF and wiring checks",
                "Independent/reference comparison across operating conditions",
            ),
        ),
        ScenarioDefinition(
            "S05",
            "نمط اضطراب جهد التغذية",
            "Electrical supply disturbance",
            "Electrical supply",
            "Engine running; load-linked voltage dip, short measurement loss",
            ("CONTROL_MODULE_VOLTAGE", "RPM", "MAF", "THROTTLE_POS"),
            ("CONTROL_MODULE_VOLTAGE", "RPM", "MAF"),
            "Voltage droop with RPM ripple and explicitly missing MAF during dip pulses",
            "pulsed",
            "Low reported module voltage synchronized with unavailable measurements",
            (
                "Supply/ground disturbance",
                "Voltage reporting bias",
                "Independent acquisition fault",
            ),
            ("External supply-voltage measurement", "Connections/ground", "Charging-system check"),
        ),
        ScenarioDefinition(
            "S06",
            "نمط عدم استقرار احتراق متقطع مشتبه",
            "Suspected intermittent combustion instability",
            "Combustion response",
            "Running engine and near-steady throttle",
            ("RPM", "ENGINE_LOAD", "SHORT_FUEL_TRIM", "LONG_FUEL_TRIM", "THROTTLE_POS"),
            ("RPM", "ENGINE_LOAD", "SHORT_FUEL_TRIM", "MAF", "INTAKE_PRESSURE"),
            "Three-second RPM depressions and load/trim rises, followed by three normal seconds",
            "intermittent",
            "Recurrent RPM/trim opposition at stable throttle",
            ("Ignition/fuel instability", "Operating transient", "Measurement inconsistency"),
            ("Available misfire counters with appropriate tool", "Ignition and fuel checks"),
        ),
        ScenarioDefinition(
            "S07",
            "نمط إشارة حساس متقطعة",
            "Intermittent sensor signal fault",
            "Signal acquisition",
            "MAP dropout/invalidity or flatline while RPM/MAF change",
            ("INTAKE_PRESSURE", "RPM", "MAF", "ENGINE_LOAD"),
            ("INTAKE_PRESSURE",),
            "Target MAP alternates with normal data, or is fixed while reference airflow varies",
            "dropout / implausible / flatline",
            "Signal issue with valid contextual references",
            ("Signal/wiring issue", "Acquisition issue", "Genuinely steady operating condition"),
            (
                "Compare sensor references",
                "Inspect wiring/acquisition",
                "Independent pressure check",
            ),
            default_start_ms=45000,
            default_duration_ms=20000,
        ),
    )
}


@dataclass(frozen=True)
class ScenarioInstance:
    scenario_id: str
    start_ms: int = 60000
    duration_ms: int = 35000
    severity: float = 1.0
    variant: str = "default"

    def __post_init__(self) -> None:
        if self.scenario_id not in SCENARIOS_MS:
            raise ValueError("Unknown scenario ID")
        if type(self.start_ms) is not int or self.start_ms < 0:
            raise ValueError("Scenario start must be nonnegative integer ms")
        if type(self.duration_ms) is not int or not 1000 <= self.duration_ms <= 90000:
            raise ValueError("Scenario duration must be 1000..90000 ms")
        if isinstance(self.severity, bool) or not 0.1 <= self.severity <= 1:
            raise ValueError("Scenario severity must be 0.1..1")
        if self.variant not in ("default", "dropout", "implausible", "flatline"):
            raise ValueError("Invalid scenario variant")
        if self.scenario_id != "S07" and self.variant != "default":
            raise ValueError("Variants apply only to the targeted signal scenario")

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms


def compatible(a: ScenarioInstance, b: ScenarioInstance) -> bool:
    overlap = max(a.start_ms, b.start_ms) < min(a.end_ms, b.end_ms)
    return not overlap or not (
        set(SCENARIOS_MS[a.scenario_id].writes) & set(SCENARIOS_MS[b.scenario_id].writes)
    )


def validate_scenarios(schedule: tuple[ScenarioInstance, ...]) -> None:
    for i, a in enumerate(schedule):
        for b in schedule[i + 1 :]:
            if not compatible(a, b):
                raise ValueError(f"Conflicting scenario writes: {a.scenario_id}, {b.scenario_id}")


def scenario_schedule(
    seed: int, duration_ms: int, max_faults: int, normal_probability: float
) -> tuple[tuple[ScenarioInstance, ...], list[dict[str, Any]]]:
    if type(max_faults) is not int or not 1 <= max_faults <= 3:
        raise ValueError("Maximum scenarios must be 1..3")
    if not 0 <= normal_probability <= 1:
        raise ValueError("Normal probability must be 0..1")
    rng = random.Random(seed ^ 0xDC003)
    schedule: list[ScenarioInstance] = []
    cycles: list[dict[str, Any]] = []
    for start in range(30000, duration_ms, 30000):
        added = []
        if rng.random() >= normal_probability:
            candidates = list(SCENARIOS_MS)
            rng.shuffle(candidates)
            wanted = rng.randint(1, min(2, max_faults))
            for sid in candidates:
                instance = ScenarioInstance(
                    sid,
                    start,
                    rng.choice((5000, 18000, 45000)),
                    rng.choice((0.6, 0.85, 1.0)),
                    rng.choice(("dropout", "implausible", "flatline"))
                    if sid == "S07"
                    else "default",
                )
                if all(compatible(instance, previous) for previous in schedule):
                    schedule.append(instance)
                    added.append(len(schedule) - 1)
                    if len(added) == wanted:
                        break
        cycles.append(
            {
                "start_ms": start,
                "new_instances": added,
                "active_instances": [
                    i for i, f in enumerate(schedule) if f.start_ms <= start < f.end_ms
                ],
            }
        )
    result = tuple(schedule)
    validate_scenarios(result)
    return result, cycles


def apply_scenarios(sample: Sample, schedule: tuple[ScenarioInstance, ...]) -> Sample:
    readings = dict(sample.readings)
    for instance in schedule:
        if not instance.start_ms <= sample.timestamp_ms < instance.end_ms:
            continue
        seconds = (sample.timestamp_ms - instance.start_ms) / 1000
        severity = instance.severity
        rpm = readings["RPM"].value or 0
        if rpm < 400:
            continue  # scenario remains scheduled, but its operating conditions do not hold
        load = readings["ENGINE_LOAD"].value or 0
        throttle = readings["THROTTLE_POS"].value or 0
        speed = readings["SPEED"].value or 0

        def put(key: str, value: float | None, quality: Quality = Quality.AVAILABLE) -> None:
            readings[key] = Reading(
                round(value, 3) if value is not None else None, readings[key].unit, quality
            )

        def add(key: str, amount: float) -> None:
            value = readings[key].value
            if value is not None:
                put(key, value + amount)

        rise = 1 - math.exp(-seconds / 1.5)
        sid = instance.scenario_id
        if sid == "S01":
            heat = severity * 48 * (1 - math.exp(-seconds / 8)) * (0.65 + load / 100)
            heat *= (0.9 + rpm / 20000 + throttle / 1000) / (1 + speed / 180)
            add("COOLANT_TEMP", heat)
            add("INTAKE_TEMP", heat * 0.08)
        elif sid == "S02":
            leak = (
                severity
                * (0.25 + 0.75 * (1 - throttle / 70))
                * (0.8 + 0.2 * math.sin(seconds / 3))
                * rise
            )
            put("MAF", (readings["MAF"].value or 0) * (1 - 0.3 * leak))
            add("INTAKE_PRESSURE", 15 * leak * (1 - load / 180))
            add("SHORT_FUEL_TRIM", 27 * leak)
            add("LONG_FUEL_TRIM", 6 * leak * (1 - math.exp(-seconds / 12)))
            add("RPM", 18 * leak * math.sin(seconds * 4))
            put("ENGINE_LOAD", min(100, load + 3 * leak))
        elif sid == "S03":
            demand = severity * (0.25 + 0.75 * min(load / 80, 1)) * rise
            add("SHORT_FUEL_TRIM", 27 * demand)
            add("LONG_FUEL_TRIM", 6 * demand * (1 - math.exp(-seconds / 15)))
            put("RPM", rpm * (1 - 0.06 * demand))
            put("ENGINE_LOAD", min(100, load + 6 * demand))
            put("MAF", (readings["MAF"].value or 0) * (1 - 0.025 * demand))
            add("INTAKE_PRESSURE", 4 * demand)
        elif sid == "S04":
            bias = severity * (0.24 + 0.06 * math.sin(seconds / 5) + 0.1 * load / 100) * rise
            put("MAF", (readings["MAF"].value or 0) * (1 - bias))
            add("INTAKE_TEMP", 3 * severity * throttle / 60 * rise)
        elif sid == "S05":
            dip = severity * (2.8 + 1.2 * load / 100 + 0.3 * max(0, 1200 - rpm) / 1200)
            pulse = 1.0 if seconds % 6 < 4 else 0.15
            add("CONTROL_MODULE_VOLTAGE", -dip * pulse)
            put("RPM", rpm * (1 - 0.05 * severity * pulse))
            if 1 <= seconds % 6 < 2:
                put("MAF", None, Quality.MISSING)
        elif sid == "S06" and seconds % 6 < 3:
            pulse = severity * (0.8 + 0.2 * math.sin(seconds * 5))
            new_rpm, new_load = rpm * (1 - 0.14 * pulse), min(100, load + 12 * pulse)
            put("RPM", new_rpm)
            put("ENGINE_LOAD", new_load)
            add("SHORT_FUEL_TRIM", 12 * pulse)
            put("MAF", expected_maf(new_rpm, new_load))
            put("INTAKE_PRESSURE", expected_map(new_load))
        elif sid == "S07":
            variant = instance.variant if instance.variant != "default" else "dropout"
            if variant == "flatline":
                put("INTAKE_PRESSURE", 45)
            elif seconds % 4 < 1:
                put(
                    "INTAKE_PRESSURE",
                    None if variant == "dropout" else -400,
                    Quality.MISSING if variant == "dropout" else Quality.INVALID,
                )
    return replace(sample, readings=readings, provenance=PROFILE)


def scenario_metadata(
    schedule: tuple[ScenarioInstance, ...], cycles: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "scenario_version": SCENARIO_VERSION,
        "calibration_profile": PROFILE,
        "scenario_schedule": [asdict(s) for s in schedule],
        "scenario_cycles": cycles,
    }
