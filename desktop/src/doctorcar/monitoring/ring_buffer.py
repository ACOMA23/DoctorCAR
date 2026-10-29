from collections import deque

from doctorcar.core.models import Sample


class TimeRingBuffer:
    def __init__(self, window_ms: int = 30_000) -> None:
        if window_ms <= 0:
            raise ValueError("window_ms must be positive")
        self.window_ms = window_ms
        self.samples: deque[Sample] = deque()

    def append_measurement(self, sample: Sample) -> None:
        if self.samples and (
            sample.session_id != self.samples[-1].session_id
            or sample.timestamp_ms <= self.samples[-1].timestamp_ms
        ):
            raise ValueError("Ring buffer requires one session in increasing time order")
        self.samples.append(sample)
        while self.samples and self.samples[0].timestamp_ms < sample.timestamp_ms - self.window_ms:
            self.samples.popleft()

    def get_pre_event_window(self, timestamp_ms: int) -> list[Sample]:
        return [
            s
            for s in self.samples
            if timestamp_ms - self.window_ms <= s.timestamp_ms <= timestamp_ms
        ]
