"""Capabilities belong to a source, never to an assumed universal vehicle."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SensorSpec:
    sensor_id: str
    arabic_name: str
    variable: str
    unit: str
    kind: str = "direct"
    source: str = "source capability; no vehicle support assumed"
    valid_range: tuple[float, float] | None = None
    missing_policy: str = "null with explicit MISSING or UNSUPPORTED"


class SensorRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, SensorSpec] = {}

    def register_sensor(self, spec: SensorSpec) -> None:
        if spec.sensor_id in self._specs:
            raise ValueError(f"Duplicate sensor: {spec.sensor_id}")
        self._specs[spec.sensor_id] = spec

    def get(self, sensor_id: str) -> SensorSpec:
        return self._specs[sensor_id]

    def all(self) -> tuple[SensorSpec, ...]:
        return tuple(self._specs.values())

    def get_supported_sensors(self, supported: set[str]) -> tuple[SensorSpec, ...]:
        return tuple(s for s in self.all() if s.sensor_id in supported)


REGISTRY = SensorRegistry()
for _id, _name, _unit in (
    ("RPM", "دوران المحرك", "rpm"),
    ("SPEED", "سرعة المركبة", "km/h"),
    ("COOLANT_TEMP", "حرارة سائل التبريد", "°C"),
    ("ENGINE_LOAD", "حمل المحرك", "%"),
    ("THROTTLE_POS", "موضع الخانق", "%"),
    ("INTAKE_PRESSURE", "ضغط هواء السحب", "kPa"),
    ("MAF", "تدفق الهواء", "g/s"),
    ("INTAKE_TEMP", "حرارة هواء السحب", "°C"),
    ("SHORT_FUEL_TRIM", "تصحيح الوقود القصير", "%"),
    ("LONG_FUEL_TRIM", "تصحيح الوقود الطويل", "%"),
    ("CONTROL_MODULE_VOLTAGE", "جهد وحدة التحكم", "V"),
):
    REGISTRY.register_sensor(SensorSpec(_id, _name, _id.lower(), _unit))
REGISTRY.register_sensor(SensorSpec("DTC", "رموز الأعطال", "dtcs", "", kind="diagnostic"))

NUMERIC_IDS = tuple(s.sensor_id for s in REGISTRY.all() if s.kind == "direct")
