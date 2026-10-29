import json
import socket
import subprocess
import sys
import threading
import time

import pytest

from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.core.session import Session
from doctorcar.sources.network_device import NetworkDeviceSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def start_device(tmp_path, *extra):
    ready = tmp_path / "ready.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "doctorcar.protocol.network_simulator",
            "--port",
            "0",
            "--speed",
            "100",
            "--history",
            str(tmp_path / "device-history.json"),
            "--ready",
            str(ready),
            *extra,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready.exists():
        process.terminate()
        raise AssertionError(process.communicate(timeout=5)[1])
    return process, json.loads(ready.read_text())["port"]


def test_separate_process_network_live_ai_history_restart_idempotent(tmp_path):
    process, port = start_device(tmp_path)
    try:
        path = tmp_path / "app.db"
        historical_ids = None
        for attempt in range(2):
            with SQLiteRepository(path) as repo:
                source = NetworkDeviceSource(port=port)
                session = Session(
                    source, repo, analyzer=AnomalyAnalyzer() if attempt == 0 else None
                )
                session.start()
                deadline = time.monotonic() + 25
                try:
                    while session.accepted < 776 and time.monotonic() < deadline:
                        session.step()
                        time.sleep(0.0001)
                    assert session.accepted == 776
                    info = source.get_device_info()
                    assert info["firmware_version"] == "software-tcp-1"
                    assert info["capabilities"]["can"] is False
                    assert source.receiver.sequence_gaps == 0
                finally:
                    session.stop()
                rows = repo.list_events()
                historical = [r["event_id"] for r in rows if r["origin"] == "HISTORICAL"]
                assert len(historical) == 2
                if attempt == 0:
                    historical_ids = historical
                    assert any(
                        repo.get_event_analysis(r["event_id"])
                        for r in rows
                        if r["origin"] == "LIVE"
                    )
                else:
                    assert historical == historical_ids
                assert all(repo.get_event_analysis(i) is None for i in historical)
                assert repo.connection.execute("pragma integrity_check").fetchone()[0] == "ok"
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_reconnect_new_boot_does_not_mix_samples(tmp_path):
    process, port = start_device(tmp_path, "--disconnect-at-ms", "10000", "--max-connections", "2")
    try:
        with SQLiteRepository(tmp_path / "reconnect.db") as repo:
            source = NetworkDeviceSource(port=port, max_reconnects=1)
            session = Session(source, repo)
            session.start()
            deadline = time.monotonic() + 15
            try:
                while session.accepted < 102 and time.monotonic() < deadline:
                    session.step()
                    time.sleep(0.001)
                assert session.accepted == 102
                assert source.reconnects == 1
                live = repo.connection.execute(
                    "select session_id,count(*) from measurements where session_id not in "
                    "(select session_id from events) group by session_id"
                ).fetchall()
                assert sorted(r[1] for r in live) == [51, 51]
                assert len([r for r in repo.list_events() if r["origin"] == "HISTORICAL"]) == 2
            finally:
                session.stop()
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_loopback_only_and_invalid_protocol_rejected():
    with pytest.raises(ValueError):
        NetworkDeviceSource("0.0.0.0")
    with pytest.raises(ValueError):
        NetworkDeviceSource("192.168.1.2")
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received = []

    def bad_server():
        with server:
            connection, _ = server.accept()
            with connection:
                connection.sendall(b'{"protocol_version":99}\n')
                connection.settimeout(0.1)
                try:
                    received.append(connection.recv(100))
                except TimeoutError:
                    received.append(b"")

    thread = threading.Thread(target=bad_server)
    thread.start()
    source = NetworkDeviceSource(port=server.getsockname()[1], max_reconnects=0)
    try:
        source.connect()
        source.start()
        with pytest.raises(ValueError):
            for _ in range(100):
                source.read_measurements()
                time.sleep(0.001)
    finally:
        source.disconnect()
        thread.join(2)
    assert received == [b""]  # Client never sent an application/vehicle command.
