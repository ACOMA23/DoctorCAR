"""Time-dependent, correlated demonstration model; not vehicle physics."""

import math
import random
import time
from uuid import uuid4

from doctorcar.core.interfaces import Capabilities, DataSource
from doctorcar.core.models import Quality, Reading, Sample, Source
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY
from doctorcar.sources.faults import (
    MODES,
    FaultInstance,
    apply_faults,
    random_schedule,
    schedule_metadata,
    validate_schedule,
)
from doctorcar.sources.scenarios import (
    ScenarioInstance,
    apply_scenarios,
    scenario_metadata,
    scenario_schedule,
    validate_scenarios,
)

SCENARIOS = ("normal", "thermal", "invalid", "dropout")


class SimulationSource(DataSource):
    NATURAL_TRIP_MS = 155_000
    CYCLE_END_S = 145.0
    DRIVE_START_S = 45.0
    DRIVE_CYCLE_S = 100.0

    def __init__(
        self,
        scenario: str = "normal",
        seed: int = 42,
        step_ms: int = 200,
        duration_ms: int = 155_000,
        *,
        mode: str | None = None,
        faults: tuple[FaultInstance, ...] = (),
        max_faults: int = 3,
        normal_probability: float = 0.25,
        scenario_family: str = "legacy",
        scenarios: tuple[ScenarioInstance, ...] = (),
        driving_scale: float = 1.0,
        warm_start: bool = False,
    ) -> None:
        if scenario not in SCENARIOS or step_ms <= 0 or duration_ms < step_ms:
            raise ValueError("Invalid simulation configuration")
        self.scenario, self.seed = scenario, seed
        if not 0.85 <= driving_scale <= 1.15:
            raise ValueError("Driving scale outside documented synthetic range")
        self.driving_scale, self.warm_start = driving_scale, warm_start
        if scenario_family not in ("legacy", "multisensor"):
            raise ValueError("Unknown simulation family")
        if scenario_family == "multisensor" and (scenario != "normal" or faults):
            raise ValueError("Multisensor scenarios cannot mix with legacy faults")
        if scenarios and (scenario_family != "multisensor" or mode != "FAULT_INJECTION"):
            raise ValueError("Explicit scenarios require multisensor FAULT_INJECTION")
        self.scenario_family = scenario_family
        self.step_ms, self.duration_ms = step_ms, duration_ms
        self.session_id = ""
        self.sequence = 0
        self.rng = random.Random(seed)
        if mode is not None and mode not in MODES:
            raise ValueError("Unknown simulation mode")
        if mode is not None and scenario != "normal":
            raise ValueError("Controlled modes cannot mix with legacy scenarios")
        if mode != "FAULT_INJECTION" and faults:
            raise ValueError("Explicit faults require FAULT_INJECTION")
        if mode == "FAULT_INJECTION" and not (faults or scenarios):
            raise ValueError("Select at least one fault")
        self.mode = mode or ("NORMAL" if scenario == "normal" else "LEGACY")
        self.max_faults, self.normal_probability = max_faults, normal_probability
        self.schedule, self.cycles = (
            random_schedule(seed, duration_ms, max_faults, normal_probability)
            if mode == "RANDOM_FAULTS" and scenario_family == "legacy"
            else (faults, [])
        )
        validate_schedule(self.schedule)
        self.scenarios, self.scenario_cycles = (
            scenario_schedule(seed, duration_ms, max_faults, normal_probability)
            if mode == "RANDOM_FAULTS" and scenario_family == "multisensor"
            else (scenarios, [])
        )
        validate_scenarios(self.scenarios)

    def get_simulation_metadata(self) -> dict[str, object]:
        metadata = schedule_metadata(
            self.mode, self.seed, self.duration_ms, self.step_ms, self.schedule, self.cycles
        )
        metadata.update(
            max_faults=self.max_faults,
            normal_probability=self.normal_probability,
            legacy_scenario=self.scenario,
            scenario_family=self.scenario_family,
        )
        if self.scenario_family == "multisensor":
            metadata.update(scenario_metadata(self.scenarios, self.scenario_cycles))
        return metadata

    def connect(self) -> None:
        self.session_id = str(uuid4())
        self.sequence, self.exhausted = 0, False
        self.rng = random.Random(self.seed)
        self.state = "CONNECTED"

    def get_capabilities(self) -> Capabilities:
        return Capabilities(frozenset((*NUMERIC_IDS, "DTC")), "SIMULATION")

    def read_measurements(self) -> Sample | None:
        if self.state != "RUNNING":
            return None
        ms = self.sequence * self.step_ms
        if ms > self.duration_ms:
            self.exhausted = True
            return None
        t = ms / 1000
        if t >= self.CYCLE_END_S and self.duration_ms > self.NATURAL_TRIP_MS:
            # Long sessions (DEF-006) keep driving: the 100 s drive cycle (45..145 s) repeats
            # with a continuous time axis, so the engine is not parked for the rest of the run.
            # The default 155 s trip keeps its natural "engine off" ending.
            tc = self.DRIVE_START_S + (t - self.DRIVE_START_S) % self.DRIVE_CYCLE_S
        else:
            tc = t
        if tc < 3:
            phase, speed, throttle, rpm = "بدء المحرك", 0.0, 12.0, 250 + t * 330
        elif tc < 35:
            phase, speed, throttle, rpm = "إحماء", 0.0, 8.0, 1100 - (tc - 3) * 8
        elif tc < 45:
            phase, speed, throttle, rpm = "خمول", 0.0, 4.0, 810.0
        elif tc < 60:
            speed = (tc - 45) * 4
            phase, throttle, rpm = "تسارع", 48.0, 1000 + speed * 32
        elif tc < 105:
            speed = 60 + math.sin(tc / 4) * 1.5
            phase, throttle, rpm = "سير مستقر", 23.0, 1000 + speed * 24
        elif tc < 125:
            speed = max(0.0, 60 - (tc - 105) * 3)
            phase, throttle, rpm = "تباطؤ", 3.0, 810 + speed * 20
        elif tc < 145:
            phase, speed, throttle, rpm = "خمول", 0.0, 4.0, 810.0
        else:
            phase, speed, throttle, rpm = "محرك متوقف", 0.0, 0.0, 0.0
        rpm = max(0.0, rpm + (self.rng.uniform(-12, 12) if rpm else 0))
        rpm *= self.driving_scale
        speed *= self.driving_scale
        throttle *= self.driving_scale
        load = min(95.0, throttle * 1.3 + speed * 0.12) if rpm else 0.0
        coolant = 22 + 68 * (1 - math.exp(-t / 35))
        if self.warm_start:
            coolant = 85 + 5 * (1 - math.exp(-t / 35))
        if self.scenario == "thermal" and 70 <= t <= 130:
            coolant += min(42, (t - 70) * 1.5, (130 - t) * 4)
        values = {
            "RPM": rpm,
            "SPEED": speed,
            "COOLANT_TEMP": coolant,
            "ENGINE_LOAD": load,
            "THROTTLE_POS": throttle,
            "INTAKE_PRESSURE": 30 + load * 0.65 if rpm else 100.0,
            "MAF": rpm * (0.002 + load * 0.00008),
            "INTAKE_TEMP": 24 + load * 0.08,
            "SHORT_FUEL_TRIM": math.sin(t / 7) * 2,
            "LONG_FUEL_TRIM": 1.5 + math.sin(t / 60) * 0.3,
            "CONTROL_MODULE_VOLTAGE": 13.9 + math.sin(t / 6) * 0.1 if rpm else 12.4,
        }
        readings = {k: Reading(round(v, 3), REGISTRY.get(k).unit) for k, v in values.items()}
        if self.scenario == "invalid" and 72 <= t <= 76:
            readings["COOLANT_TEMP"] = Reading(-999.0, "°C")
        if self.scenario == "dropout" and 72 <= t <= 80:
            readings["COOLANT_TEMP"] = Reading(None, "°C", Quality.MISSING)
        result = Sample(
            self.session_id,
            Source.SIMULATION,
            self.sequence,
            ms,
            readings,
            phase=phase,
            received_at_ms=time.time_ns() // 1_000_000,
            dtc_quality=Quality.AVAILABLE,
        )
        self.sequence += 1
        if self.scenario_family == "multisensor":
            return apply_scenarios(result, self.scenarios)
        return apply_faults(result, self.schedule)
