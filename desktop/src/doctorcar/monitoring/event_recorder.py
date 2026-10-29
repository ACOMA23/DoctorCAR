from uuid import NAMESPACE_URL, uuid5

from doctorcar.core.interfaces import EventSink
from doctorcar.core.models import Event, Sample, Trigger
from doctorcar.monitoring.ring_buffer import TimeRingBuffer


class EventRecorder:
    def __init__(self, repository: EventSink, pre_ms: int = 30_000, post_ms: int = 30_000) -> None:
        self.repository = repository
        self.buffer = TimeRingBuffer(pre_ms)
        self.post_ms = post_ms
        self.active: dict[str, Event] = {}

    def append_measurement(self, sample: Sample, triggers: tuple[Trigger, ...]) -> list[Event]:
        self.buffer.append_measurement(sample)
        for event in self.active.values():
            if sample.timestamp_ms <= event.trigger.timestamp_ms + self.post_ms:
                event.samples.append(sample)
        # Close events whose post window ended with this sample BEFORE looking at new triggers:
        # a trigger of the same kind at exactly T+post is a new fault, not the finished event
        # (DEF-005).
        completed = []
        for event in list(self.active.values()):
            if sample.timestamp_ms >= event.trigger.timestamp_ms + self.post_ms:
                self.finalize_event(event, "COMPLETE")
                completed.append(event)
        for trigger in triggers:
            if not any(e.trigger.kind == trigger.kind for e in self.active.values()):
                self.start_event(sample, trigger)
        for event in self.active.values():
            self.repository.save_event(event)
        return completed

    def start_event(self, sample: Sample, trigger: Trigger) -> Event:
        event_id = str(
            uuid5(
                NAMESPACE_URL,
                f"doctorcar:{sample.session_id}:{trigger.kind}:{trigger.timestamp_ms}",
            )
        )
        event = Event(
            event_id,
            sample.session_id,
            trigger,
            self.buffer.get_pre_event_window(trigger.timestamp_ms),
        )
        if event.samples[0].timestamp_ms > trigger.timestamp_ms - self.buffer.window_ms:
            event.limitations.append(
                "نافذة ما قبل الحدث أقصر من 30 ثانية؛ حُفظت البيانات المتاحة فقط"
            )
        self.active[event_id] = event
        self.repository.save_event(event)
        return event

    def finalize_event(self, event: Event, status: str) -> None:
        event.status = status
        event.end_ms = event.samples[-1].timestamp_ms
        if status == "PARTIAL":
            event.limitations.append("توقف المصدر قبل اكتمال 30 ثانية بعد الحدث")
        self.repository.save_event(event)
        self.active.pop(event.event_id, None)

    def stop(self) -> None:
        for event in list(self.active.values()):
            self.finalize_event(event, "PARTIAL")
