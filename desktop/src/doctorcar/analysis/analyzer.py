"""Stateful streaming inference; failures become unavailable, never normal."""

from collections import deque
from dataclasses import dataclass
from typing import Any

from doctorcar.analysis.model import AnomalyModel
from doctorcar.analysis.windows import WindowBuilder
from doctorcar.core.models import Sample, Trigger

HISTORY_WINDOWS = 64


@dataclass(frozen=True)
class DetectionPolicy:
    """Temporal persistence and debounce shared by the application and offline evaluation."""

    consecutive: int = 3
    hysteresis: float = 0.02

    def __post_init__(self) -> None:
        if not 1 <= self.consecutive <= 10 or not 0 <= self.hysteresis <= 0.2:
            raise ValueError("Invalid detection policy")


class PersistenceGate:
    """Fires once after N consecutive anomalous windows, then latches until clearly normal."""

    def __init__(self, threshold: float, policy: DetectionPolicy) -> None:
        self.threshold, self.policy = threshold, policy
        self.consecutive = 0
        self.latched = False

    def reset(self) -> None:
        self.consecutive, self.latched = 0, False

    def update(self, score: float | None) -> bool:
        """Feed one window score; None means no valid window and breaks the run."""
        if score is None:
            self.consecutive = 0
            return False
        anomalous = score > self.threshold
        self.consecutive = self.consecutive + 1 if anomalous else 0
        fire = self.consecutive >= self.policy.consecutive and not self.latched
        if fire:
            self.latched = True
        if not anomalous and score < self.threshold - self.policy.hysteresis:
            self.latched = False
        return fire


class AnomalyAnalyzer:
    def __init__(self, model: AnomalyModel | None = None) -> None:
        self.model = model or AnomalyModel()
        policy = self.model.policy
        self.policy = DetectionPolicy(int(policy["consecutive"]), float(policy["hysteresis"]))
        self.builder = WindowBuilder()
        self.gate = PersistenceGate(float(self.model.metadata["threshold"]), self.policy)
        self.last_result: dict[str, Any] = {"decision": "INSUFFICIENT_DATA"}
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_WINDOWS)
        self.session_id = ""
        # Two missed strides are tolerated; older results never describe the present.
        self.max_age_ms = 2 * self.builder.config.stride_ms

    @property
    def consecutive(self) -> int:
        return self.gate.consecutive

    @property
    def latched(self) -> bool:
        return self.gate.latched

    def push(self, sample: Sample) -> tuple[dict[str, Any] | None, Trigger | None]:
        if sample.session_id != self.session_id:
            self.gate.reset()
            self.history.clear()
            self.session_id = sample.session_id
        window = self.builder.push(sample)
        if window is None:
            return None, None
        result = self.model.infer(window)
        self.last_result = result
        self.history.append(result)
        score = result.get("score")
        fired = self.gate.update(float(score) if score is not None else None)
        trigger = None
        if fired:
            trigger = Trigger(
                "ML_ANOMALY",
                "نمط غير معتاد في مجموعة من القياسات",
                f"IsolationForest: {self.policy.consecutive} نوافذ متتالية فوق العتبة؛ "
                "لا يحدد قطعة تالفة",
                result["model_version"],
                sample.timestamp_ms,
                (f"score={result['score']:.6f}", f"threshold={result['threshold']:.6f}"),
            )
        return result, trigger

    def latest_before(self, session_id: str, time_ms: int) -> dict[str, Any] | None:
        """Newest analysis whose window ended at or before time_ms, same session, not stale."""
        for result in reversed(self.history):
            if result.get("session_id") != session_id:
                continue
            end = result.get("end_ms")
            if end is not None and end <= time_ms:
                return result if time_ms - end <= self.max_age_ms else None
        return None

    def evaluate_window(self, samples: tuple[Sample, ...]) -> tuple[Trigger, ...]:
        triggers = []
        for sample in samples:
            _, trigger = self.push(sample)
            if trigger:
                triggers.append(trigger)
        return tuple(triggers)

    def explain(self, result: dict[str, Any]) -> dict[str, Any]:
        from doctorcar.analysis.explanation import explain

        return explain(self.model, result)
