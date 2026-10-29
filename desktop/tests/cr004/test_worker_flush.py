import time

from PySide6.QtWidgets import QApplication

from doctorcar.sources.simulation import SimulationSource
from doctorcar.ui.worker import BackendWorker


def test_last_sample_is_published_after_a_burst_without_next_sample(tmp_path, monkeypatch):
    class IdleAfterBurst(SimulationSource):
        def read_measurements(self):
            if self.sequence >= 2:
                return None
            return super().read_measurements()

    monkeypatch.setattr("doctorcar.ui.worker.create_source", lambda args: IdleAfterBurst())
    app = QApplication.instance() or QApplication([])
    worker = BackendWorker(tmp_path / "flush.db")
    snapshots = []
    worker.snapshot.connect(lambda s: snapshots.append(s.timestamp_ms))
    worker.start()
    worker.submit("start", source="simulation", speed=30)
    deadline = time.monotonic() + 5
    try:
        while (not snapshots or snapshots[-1] != 200) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert snapshots[-1] == 200
    finally:
        worker.shutdown()
        assert worker.wait(5000)
