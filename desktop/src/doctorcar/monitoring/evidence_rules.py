"""Numeric rules used by EventDetector and EvidenceBuilder, not another engine.

Calibration: DoctorCAR's public correlated toy model only. All inputs are observed
samples. There are no imports of generators, schedules, fault IDs, or ground truth.
"""

import math
from dataclasses import dataclass
from statistics import mean

from doctorcar.core.models import Quality, Sample
from doctorcar.core.sensor_registry import REGISTRY
from doctorcar.core.simulation_profile import PROFILE, expected_maf, expected_map

RULE_VERSION_MS = "correlated-evidence-1"
WINDOW_MS = 8000


@dataclass(frozen=True)
class EvidenceRule:
    rule_id: str
    pattern_ar: str
    pattern_en: str
    system_ar: str
    system_en: str
    required: tuple[str, ...]
    operating_conditions: str
    numeric_conditions: str
    causes: tuple[tuple[str, str], ...]
    checks: tuple[tuple[str, str], ...]
    missing: tuple[tuple[str, str], ...]
    window_ms: int = WINDOW_MS
    validity: str = "Known simulation calibration; available finite readings with registry units"


AIR = ("MAF", "INTAKE_PRESSURE", "RPM", "ENGINE_LOAD", "THROTTLE_POS")
TRIMS = ("SHORT_FUEL_TRIM", "LONG_FUEL_TRIM")
RULES = {
    r.rule_id: r
    for r in (
        EvidenceRule(
            "MS_THERMAL",
            "نمط حراري متصاعد تحت حمل",
            "Rising thermal pattern under load",
            "منظومة التبريد أو قياس الحرارة",
            "Cooling or temperature measurement",
            ("COOLANT_TEMP", "RPM", "SPEED", "ENGINE_LOAD", "THROTTLE_POS"),
            "Running engine, mean load > 5%; recent temperature rise",
            "temperature >=105°C; slope >0.12°C/s; >=1s valid observations",
            (
                ("احتمال انخفاض فعالية التبريد", "Possible reduced cooling effectiveness"),
                ("احتمال انحراف قياس الحرارة", "Possible temperature measurement bias"),
            ),
            (
                (
                    "فحص مستوى السائل وحركة المروحة وفعالية الدورة؛ قارن بحرارة مستقلة",
                    "Check coolant level, fan and circulation; compare an independent temperature",
                ),
            ),
            (
                (
                    "مواصفات المركبة وقياس حرارة مستقل",
                    "Vehicle specifications and independent temperature",
                ),
            ),
        ),
        EvidenceRule(
            "MS_AIR_FUEL",
            "عدم توافق الهواء وتصحيح الوقود",
            "Air/fuel relationship mismatch",
            "منظومة الهواء والوقود",
            "Air and fuel system",
            AIR + TRIMS,
            "Running engine with >5% throttle",
            "STFT >10%; MAF residual <-12%; MAP residual >4kPa",
            (
                ("احتمال تسرب هواء غير مقاس", "Possible unmetered intake air"),
                (
                    "احتمال انحراف قياس الهواء أو قصور الوقود",
                    "Possible air measurement bias or fuel limitation",
                ),
            ),
            (
                (
                    "اختبار تسرب مناسب وفحص الأنابيب؛ قارن MAF/MAP وFuel Trims عبر أحمال مختلفة",
                    (
                        "Suitable leak test and hose inspection; compare "
                        "MAF/MAP and trims across loads"
                    ),
                ),
            ),
            (
                (
                    "اختبار تسرب مستقل وضغط الوقود الفعلي غير متاحين",
                    "Independent leak test and actual fuel pressure unavailable",
                ),
            ),
        ),
        EvidenceRule(
            "MS_FUEL_RESPONSE",
            "تصحيح وقود مرتفع تحت حمل مع مراجع هواء متقاربة",
            "High fuel correction under load with consistent air references",
            "منظومة الهواء والوقود",
            "Air and fuel system",
            AIR + TRIMS,
            "Running engine, mean load >=25%",
            "STFT >10%; |MAF residual|<15%; |MAP residual|<4kPa",
            (
                ("احتمال قصور إمداد الوقود", "Possible fuel supply limitation"),
                ("احتمال تسرب هواء أو انحراف قياس", "Possible intake leak or measurement bias"),
            ),
            (
                (
                    (
                        "قياس ضغط الوقود بأداة خارج OBD مناسبة ومراجعة "
                        "الإمداد؛ قارن التصحيحات عبر الأحمال"
                    ),
                    (
                        "Measure actual fuel pressure with suitable external "
                        "equipment; inspect supply and compare loads"
                    ),
                ),
            ),
            (
                (
                    "لا يوجد Fuel Pressure PID أو قياس ضغط فعلي",
                    "No fuel pressure PID or actual pressure measurement",
                ),
            ),
        ),
        EvidenceRule(
            "MS_AIRFLOW",
            "عدم اتساق قياس تدفق الهواء مع المراجع",
            "Airflow measurement inconsistent with references",
            "قياس الهواء",
            "Air measurement",
            AIR + ("SHORT_FUEL_TRIM",),
            "Running engine, throttle >5%",
            "MAF residual <-18%; |MAP residual|<3kPa; |STFT|<8%",
            (
                ("احتمال انحراف قياس MAF أو توصيلاته", "Possible MAF reporting or wiring bias"),
                (
                    "احتمال تغير حقيقي للهواء أو عدم ملاءمة النموذج المرجعي",
                    "Possible actual airflow change or reference-model mismatch",
                ),
            ),
            (
                (
                    "مراجعة MAF والتوصيلات ومقارنة MAF/MAP وRPM والخانق في عدة ظروف",
                    "Inspect MAF and wiring; compare MAF/MAP, RPM and throttle across conditions",
                ),
            ),
            (
                (
                    "قياس مستقل لتدفق الهواء ومواصفات المحرك",
                    "Independent airflow measurement and engine specification",
                ),
            ),
        ),
        EvidenceRule(
            "MS_SUPPLY",
            "جهد منخفض متزامن مع اضطراب قياس",
            "Low voltage with concurrent measurement disturbance",
            "التغذية أو اكتساب البيانات",
            "Supply or data acquisition",
            ("CONTROL_MODULE_VOLTAGE", "RPM", "THROTTLE_POS"),
            "Engine running, >1s observed",
            "voltage <11.5V and concurrent missing measurements; not a transport-loss inference",
            (
                ("احتمال اضطراب تغذية أو أرضي", "Possible supply or ground disturbance"),
                (
                    "احتمال خطأ إبلاغ الجهد أو اكتساب بيانات مستقل",
                    "Possible voltage-reporting or separate acquisition issue",
                ),
            ),
            (
                (
                    "قياس جهد التغذية بأداة مستقلة وفحص التوصيلات والأرضي والشحن حسب الأدلة",
                    (
                        "Measure supply voltage independently; inspect "
                        "connections, ground and charging as warranted"
                    ),
                ),
            ),
            (
                (
                    "جهد مستقل وتيار البطارية غير مقاسين",
                    "Independent voltage and battery current are not measured",
                ),
            ),
        ),
        EvidenceRule(
            "MS_COMBUSTION",
            "استجابة متقطعة غير مستقرة عند خانق مستقر",
            "Intermittent unstable response at stable throttle",
            "استقرار الاحتراق أو القياس",
            "Combustion stability or measurement",
            ("RPM", "ENGINE_LOAD", "SHORT_FUEL_TRIM", "THROTTLE_POS"),
            "Running engine with throttle range <=2 points",
            (
                "RPM range >100; load range >5; trim range >4; "
                "RPM/trim correlation <-0.5; >=2 reversals"
            ),
            (
                ("احتمال عدم استقرار اشتعال أو وقود", "Possible ignition or fuel instability"),
                (
                    "احتمال تغير تشغيل أو عدم اتساق قياس",
                    "Possible operating transient or measurement inconsistency",
                ),
            ),
            (
                (
                    (
                        "قراءة عدادات Misfire المتاحة بأداة مناسبة وفحص "
                        "الاشتعال والوقود؛ لا تحديد أسطوانة"
                    ),
                    (
                        "Read available misfire counters with a suitable tool; "
                        "inspect ignition/fuel; no cylinder identification"
                    ),
                ),
            ),
            (
                (
                    "لا عدادات Misfire أو دليل أسطوانة أو DTC مؤكد",
                    "No misfire counters, cylinder evidence or confirmed DTC",
                ),
            ),
        ),
        EvidenceRule(
            "MS_SIGNAL",
            "فقد إشارة أو ثبات مشتبه مع تغير المراجع",
            "Signal loss or suspected flatline with changing references",
            "إشارة الحساس أو الاكتساب",
            "Sensor signal or acquisition",
            ("RPM", "MAF", "ENGINE_LOAD"),
            "Valid airflow references; target MAP may be missing/invalid",
            "MAP missing/invalid OR >=3s range<0.03kPa with RPM range>150 and MAF range>1g/s",
            (
                (
                    "احتمال خلل إشارة أو توصيل أو اكتساب",
                    "Possible signal, wiring or acquisition issue",
                ),
                (
                    "احتمال ظروف تشغيل ثابتة أو مرجع غير ملائم",
                    "Possible steady operation or unsuitable reference",
                ),
            ),
            (
                (
                    "مقارنة مراجع الحساس وفحص التوصيلات وتوقيت الاكتساب؛ قياس ضغط مستقل عند الحاجة",
                    (
                        "Compare references, inspect wiring and acquisition "
                        "timing; independent pressure if needed"
                    ),
                ),
            ),
            (
                (
                    "التحقق المستقل من الضغط والتوصيلات غير متاح",
                    "Independent pressure and wiring verification unavailable",
                ),
            ),
        ),
    )
}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    start_ms: int
    end_ms: int
    metrics: dict[str, float]
    contradicting_evidence: tuple[str, ...] = ()

    @property
    def supporting_evidence(self) -> tuple[str, ...]:
        return tuple(
            f"{key}={value:.4f} [{self.start_ms}..{self.end_ms} ms]"
            for key, value in self.metrics.items()
        )


def valid_value(sample: Sample, key: str) -> float | None:
    reading = sample.readings.get(key)
    if reading and reading.quality == Quality.AVAILABLE and reading.unit == REGISTRY.get(key).unit:
        return reading.value
    return None


def correlation(a: list[float], b: list[float]) -> float:
    am, bm = mean(a), mean(b)
    numerator = sum((x - am) * (y - bm) for x, y in zip(a, b, strict=True))
    denominator = math.sqrt(sum((x - am) ** 2 for x in a) * sum((y - bm) ** 2 for y in b))
    return numerator / denominator if denominator else 0


def map_reference_frozen(rows: list[Sample], current_ms: int, tail_ms: int = 3000) -> bool:
    """MAP stayed constant to <0.03 kPa for >=3 s while load or RPM demonstrably moved.

    A healthy manifold pressure follows load (it tracks the calibrated expected_map(load)
    exactly in the calibration trips), so a frozen value is an objective observation that the
    MAP *reference* cannot be trusted. It is evidence about the sensor, never about the engine.
    """
    tail = [s for s in rows if current_ms - s.timestamp_ms <= tail_ms]
    if len(tail) < 3 or tail[-1].timestamp_ms - tail[0].timestamp_ms < tail_ms:
        return False
    pressure = [v for s in tail if (v := valid_value(s, "INTAKE_PRESSURE")) is not None]
    load = [v for s in tail if (v := valid_value(s, "ENGINE_LOAD")) is not None]
    rpm = [v for s in tail if (v := valid_value(s, "RPM")) is not None]
    if len(pressure) != len(tail) or not load or not rpm:
        return False
    # The calibrated model says how far MAP must move for the observed load change; a reading
    # that moved <0.03 kPa although >=0.05 kPa was expected (or while RPM swung >150) is frozen.
    expected_change = abs(expected_map(max(load)) - expected_map(min(load)))
    return max(pressure) - min(pressure) < 0.03 and (
        expected_change >= 0.05 or max(rpm) - min(rpm) > 150
    )


def evaluate_relations(samples: tuple[Sample, ...]) -> tuple[Finding, ...]:
    if not samples or samples[-1].provenance != PROFILE:
        return ()
    current = samples[-1]
    window = tuple(
        s
        for s in samples
        if s.session_id == current.session_id
        and s.provenance == PROFILE
        and 0 <= current.timestamp_ms - s.timestamp_ms <= WINDOW_MS
    )
    findings = []
    for rule in RULES.values():
        rows = [s for s in window if all(valid_value(s, k) is not None for k in rule.required)]
        if (
            len(rows) < 3
            or rows[-1] is not current
            or rows[-1].timestamp_ms - rows[0].timestamp_ms < 1000
            or any(
                b.timestamp_ms - a.timestamp_ms > 1500 for a, b in zip(rows, rows[1:], strict=False)
            )
        ):
            continue

        def values(key: str, rows: list[Sample] = rows) -> list[float]:
            return [v for s in rows if (v := valid_value(s, key)) is not None]

        rpm = values("RPM")
        if not rpm or min(rpm) < 400:
            continue
        load, throttle = values("ENGINE_LOAD"), values("THROTTLE_POS")
        metrics: dict[str, float] = {}
        contrary: tuple[str, ...] = ()
        kind = rule.rule_id
        if kind == "MS_THERMAL":
            temps, speed = values("COOLANT_TEMP"), values("SPEED")
            slope = (temps[-1] - temps[0]) / ((rows[-1].timestamp_ms - rows[0].timestamp_ms) / 1000)
            if temps[-1] >= 105 and slope > 0.12 and mean(load) > 5:
                metrics = {
                    "coolant_current_C": temps[-1],
                    "coolant_slope_C_per_s": slope,
                    "load_mean_pct": mean(load),
                    "speed_mean_km_h": mean(speed),
                    "rpm_mean": mean(rpm),
                    "throttle_mean_pct": mean(throttle),
                }
        elif kind in ("MS_AIR_FUEL", "MS_FUEL_RESPONSE", "MS_AIRFLOW"):
            maf = values("MAF")
            pressure = values("INTAKE_PRESSURE")
            short, long = values("SHORT_FUEL_TRIM"), values("LONG_FUEL_TRIM")
            residual = mean(
                (m - expected_maf(r, demand)) / max(expected_maf(r, demand), 0.1)
                for m, r, demand in zip(maf, rpm, load, strict=True)
            )
            map_residual = mean(
                p - expected_map(demand) for p, demand in zip(pressure, load, strict=True)
            )
            stft = mean(short)
            map_frozen = map_reference_frozen(rows, current.timestamp_ms)
            match = (
                kind == "MS_AIR_FUEL"
                and stft > 10
                and residual < -0.12
                and map_residual > 4
                and min(throttle) > 5
                or kind == "MS_FUEL_RESPONSE"
                and stft > 10
                and abs(residual) < 0.15
                and abs(map_residual) < 4
                and mean(load) >= 25
                and short[-1] > 10
                and all(
                    abs(p - expected_map(demand)) < 4
                    for p, demand in zip(pressure[-3:], load[-3:], strict=True)
                )
                or kind == "MS_AIRFLOW"
                and residual < -0.18
                and (abs(map_residual) < 3 or map_frozen)
                and abs(stft) < 8
                and min(throttle) > 5
            )
            if match:
                metrics = {
                    "maf_residual_pct": 100 * residual,
                    "map_residual_kPa": map_residual,
                    "stft_mean_pct": stft,
                    "load_mean_pct": mean(load),
                    "rpm_mean": mean(rpm),
                    "throttle_mean_pct": mean(throttle),
                }
                if long:
                    metrics["ltft_mean_pct"] = mean(long)
                if kind == "MS_AIRFLOW":
                    contrary = (
                        f"STFT mean={stft:.3f}%; large positive correction is not observed",
                    )
                    if map_frozen and abs(map_residual) >= 3:
                        # DEF-004: the MAP reference is unusable, so the leak-vs-MAF-bias
                        # distinction is NOT supported by pressure evidence; say so explicitly.
                        metrics["map_reference_frozen"] = 1.0
                        contrary += (
                            "INTAKE_PRESSURE is frozen (<0.03 kPa change for >=3 s while load/RPM "
                            "moved); the MAP reference is unreliable, so this finding rests on the "
                            "MAF deficit alone",
                        )
                elif kind == "MS_FUEL_RESPONSE":
                    contrary = (
                        f"MAP residual={map_residual:.3f} kPa; "
                        "large intake-pressure mismatch absent",
                    )
        elif kind == "MS_SUPPLY":
            voltage = values("CONTROL_MODULE_VOLTAGE")
            concurrent = sum(
                1
                for s in rows
                if (observed_voltage := valid_value(s, "CONTROL_MODULE_VOLTAGE")) is not None
                and observed_voltage < 11.5
                and any(r.quality == Quality.MISSING for r in s.readings.values())
            )
            if min(voltage) < 11.5 and concurrent:
                metrics = {
                    "voltage_min_V": min(voltage),
                    "concurrent_low_voltage_missing_samples": float(concurrent),
                    "rpm_range": max(rpm) - min(rpm),
                    "throttle_range_pct": max(throttle) - min(throttle),
                }
        elif kind == "MS_COMBUSTION":
            short = values("SHORT_FUEL_TRIM")
            corr = correlation(rpm, short)
            deltas = [b - a for a, b in zip(rpm, rpm[1:], strict=False)]
            reversals = sum(a * b < 0 for a, b in zip(deltas, deltas[1:], strict=False))
            if (
                max(rpm) - min(rpm) > 100
                and max(load) - min(load) > 5
                and max(short) - min(short) > 4
                and max(throttle) - min(throttle) <= 2
                and corr < -0.5
                and reversals >= 2
            ):
                metrics = {
                    "rpm_range": max(rpm) - min(rpm),
                    "load_range_pct": max(load) - min(load),
                    "stft_range_pct": max(short) - min(short),
                    "rpm_stft_correlation": corr,
                    "throttle_range_pct": max(throttle) - min(throttle),
                    "rpm_reversals": float(reversals),
                }
        elif kind == "MS_SIGNAL":
            pressure = values("INTAKE_PRESSURE")
            bad = sum(
                s.readings.get("INTAKE_PRESSURE") is not None
                and s.readings["INTAKE_PRESSURE"].quality in (Quality.MISSING, Quality.INVALID)
                for s in rows
            )
            maf = values("MAF")
            span = rows[-1].timestamp_ms - rows[0].timestamp_ms
            flat = (
                len(pressure) == len(rows)
                and span >= 3000
                and max(pressure) - min(pressure) < 0.03
                and (
                    (max(rpm) - min(rpm) > 150 and max(maf) - min(maf) > 1)
                    or map_reference_frozen(rows, current.timestamp_ms)
                )
            )
            if bad or flat:
                metrics = {
                    "map_missing_invalid_samples": float(bad),
                    "rpm_range": max(rpm) - min(rpm),
                    "maf_range_g_s": max(maf) - min(maf),
                    "reference_samples": float(len(rows)),
                }
                if pressure:
                    metrics["map_range_kPa"] = max(pressure) - min(pressure)
        if metrics:
            findings.append(
                Finding(kind, rows[0].timestamp_ms, current.timestamp_ms, metrics, contrary)
            )
    return tuple(findings)


def classify_sensors(samples: tuple[Sample, ...], findings: tuple[Finding, ...]) -> dict[str, str]:
    if not samples:
        return {}
    current = samples[-1]
    states = {key: "UNRESOLVED" for key in current.readings}
    if current.provenance != PROFILE:
        return states
    for key, reading in current.readings.items():
        if reading.quality == Quality.INVALID:
            states[key] = "IMPLAUSIBLE_SIGNAL"
        elif reading.quality == Quality.MISSING:
            states[key] = "SIGNAL_LOSS_OR_SUSPECTED_FLATLINE"
    if len(samples) >= 3 and samples[-1].timestamp_ms - samples[0].timestamp_ms >= 1000:
        if all(valid_value(current, key) is not None for key in AIR + TRIMS):
            rpm = valid_value(current, "RPM")
            load = valid_value(current, "ENGINE_LOAD")
            maf = valid_value(current, "MAF")
            pressure = valid_value(current, "INTAKE_PRESSURE")
            short = valid_value(current, "SHORT_FUEL_TRIM")
            long = valid_value(current, "LONG_FUEL_TRIM")
            assert None not in (rpm, load, maf, pressure, short, long)
            assert rpm is not None and load is not None and maf is not None
            assert pressure is not None and short is not None and long is not None
            if (
                rpm > 400
                and abs(maf - expected_maf(rpm, load)) / max(0.1, expected_maf(rpm, load)) < 0.1
                and abs(pressure - expected_map(load)) < 3
                and abs(short) < 8
                and abs(long) < 8
            ):
                for key in AIR + TRIMS:
                    states[key] = "NORMAL"
        coolant, voltage = (
            valid_value(current, "COOLANT_TEMP"),
            valid_value(current, "CONTROL_MODULE_VOLTAGE"),
        )
        expected_temperature = 22 + 68 * (1 - math.exp(-current.timestamp_ms / 35000))
        if (
            coolant is not None
            and abs(coolant - expected_temperature) <= 5
            and valid_value(current, "RPM") is not None
        ):
            states["COOLANT_TEMP"] = "NORMAL"
        if (
            voltage is not None
            and 12.5 <= voltage <= 14.5
            and (valid_value(current, "RPM") or 0) > 400
        ):
            states["CONTROL_MODULE_VOLTAGE"] = "NORMAL"
    targets = {
        "MS_THERMAL": ("COOLANT_TEMP",),
        "MS_AIR_FUEL": ("MAF", "INTAKE_PRESSURE", *TRIMS),
        "MS_FUEL_RESPONSE": TRIMS,
        "MS_AIRFLOW": ("MAF",),
        "MS_SUPPLY": ("CONTROL_MODULE_VOLTAGE",),
        "MS_COMBUSTION": ("RPM", "ENGINE_LOAD", "SHORT_FUEL_TRIM"),
        "MS_SIGNAL": (),
    }
    for finding in findings:
        for key in targets[finding.rule_id]:
            if valid_value(current, key) is not None:
                states[key] = "ABNORMAL_OPERATION"
        if finding.rule_id == "MS_SIGNAL":
            states["INTAKE_PRESSURE"] = (
                "IMPLAUSIBLE_SIGNAL"
                if current.readings["INTAKE_PRESSURE"].quality == Quality.INVALID
                else "SIGNAL_LOSS_OR_SUSPECTED_FLATLINE"
            )
        if finding.rule_id == "MS_AIRFLOW":
            states["MAF"] = "IMPLAUSIBLE_SIGNAL"
    # A missing reference makes related normality undecidable, not mechanically normal.
    for rule in RULES.values():
        if any(valid_value(current, key) is None for key in rule.required):
            for key in rule.required:
                if states.get(key) == "NORMAL":
                    states[key] = "UNRESOLVED"
    return states
