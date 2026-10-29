"""QA-IOT: protocol conformance, scripted network/serial failures and real loopback-device E2E."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from itertools import islice
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402

import serial  # noqa: E402

from doctorcar.core.models import Event  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.protocol.codec import encode_message  # noqa: E402
from doctorcar.protocol.receiver import ProtocolReceiver  # noqa: E402
from doctorcar.protocol.simulator import device_messages  # noqa: E402
from doctorcar.sources.device_simulator import historical_device_messages, historical_events  # noqa: E402
from doctorcar.sources.network_device import NetworkDeviceSource  # noqa: E402
from doctorcar.sources.serial_device import ProtocolFileSource, SerialDeviceSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("gate7")
folder = EVIDENCE / "gate7"
folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("iot")
base = list(islice(device_messages(), 14))  # HELLO, CAPABILITIES, SAMPLE/HEARTBEAT ...
samples_only = [m for m in base if m["type"] == "SAMPLE"]


def feed(msgs, raw=()):
    r = ProtocolReceiver()
    for m in msgs:
        r.feed(m if isinstance(m, bytes) else encode_message(m))
    for b in raw:
        r.feed(b)
    return r


def err(r):
    return list(r.errors)


def mut(m, **k):
    out = json.loads(json.dumps(m))
    out.update(k)
    return out


def raw_line(m):
    """Serialize without the product encoder so invalid versions can be sent."""
    return (json.dumps(m, separators=(",", ":")) + "\n").encode()


# ---------------------------------------------------------------------------- receiver conformance
r = feed(base)
reg.check("QA-IOT-001", "FR-012", "Valid HELLO + CAPABILITIES + samples are accepted", "generated device stream", "samples queued, no errors, sensors advertised",
          len(r.samples) == len(samples_only) and not r.errors and r.sensors is not None, f"samples={len(r.samples)} errors={err(r)} sensors={len(r.sensors or [])}")
minimal = feed([], raw=[b'{"protocol_version":1,"type":"HELLO"}\n'])
reg.check("QA-IOT-002", "FR-012", "Python parser rejects an incomplete HELLO envelope (the case A07 says the C firmware accepts)", '{"protocol_version":1,"type":"HELLO"}',
          "error recorded, no handshake", bool(minimal.errors) and minimal.identity is None, f"errors={err(minimal)} identity={minimal.identity}",
          notes="Firmware side stays static-review only (NOT TESTED).")
cases = {
    "version 2": feed([], raw=[raw_line(mut(base[0], protocol_version=2))]),
    "version true": feed([], raw=[raw_line(mut(base[0], protocol_version=True))]),
    "invalid JSON": feed([], raw=[b"{not json}\n"]),
    "duplicate key": feed([], raw=[b'{"protocol_version":1,"protocol_version":1,"type":"HELLO"}\n']),
    "NaN constant": feed([], raw=[b'{"protocol_version":1,"type":"HELLO","payload":{"x":NaN}}\n']),
    "no payload": feed([], raw=[raw_line({k: v for k, v in base[0].items() if k != "payload"})]),
    "no device_id": feed([], raw=[raw_line({k: v for k, v in base[0].items() if k != "device_id"})]),
    "missing newline then oversize": feed([], raw=[b"x" * 5000 + b"\n"]),
    "sample before handshake": feed([samples_only[0]]),
    "CAPABILITIES without sensors": feed([base[0]], raw=[raw_line(mut(base[1], payload={"can": False}))]),
}
rejected = {k: bool(v.errors) or (v.identity is None and not v.samples) for k, v in cases.items()}
reg.check("QA-IOT-003", "FR-012", "Malformed protocol input is rejected without crashing the receiver", "10 malformed inputs (version, JSON, duplicate key, NaN, missing fields, oversize, order)",
          "each produces an error or no state", all(rejected.values()), json.dumps({k: (v, err(cases[k])[:1]) for k, v in rejected.items()}, ensure_ascii=False))
big = feed(base[:2], raw=[b"y" * 9000, b"\n"])
after = feed(base[:2] + [], raw=[b"y" * 9000 + b"\n"])
after.feed(encode_message(samples_only[0]))
reg.check("QA-IOT-004", "FR-012", "A very large line is dropped and the stream recovers on the next valid message", "9000-byte line then a valid SAMPLE",
          "oversized error then the sample is accepted", "oversized_line" in err(after) and len(after.samples) == 1, f"errors={err(after)} samples={len(after.samples)}")
dup = feed(base[:3] + [base[2]])
gap = feed(base[:2] + [mut(samples_only[0]), mut(samples_only[2])])
reg.check("QA-IOT-005", "FR-012", "Duplicate sequence is suppressed (one sample), a skipped sequence is counted but data kept", "SAMPLE twice; sequence 2 -> 4",
          "1 sample for the duplicate; sequence_gaps==1 for the gap", len(dup.samples) == 1 and gap.sequence_gaps == 1 and len(gap.samples) == 2,
          f"duplicate samples={len(dup.samples)} errors={err(dup)}; gap: gaps={gap.sequence_gaps} samples={len(gap.samples)}")
unknown = json.loads(json.dumps(samples_only[0]))
unknown["payload"]["sample"]["readings"]["FOO"] = {"value": 1.0, "unit": "x", "quality": "AVAILABLE"}
boolean = json.loads(json.dumps(samples_only[0]))
boolean["payload"]["sample"]["readings"]["RPM"]["value"] = True
nanv = encode_message(samples_only[0]).replace(b'"RPM": {"value": ', b'"RPM": {"value": NaN, "x": ', 1) if b'"RPM": {"value": ' in encode_message(samples_only[0]) else b""
t = {"unknown sensor": feed(base[:2], raw=[raw_line(unknown)]), "boolean value": feed(base[:2], raw=[raw_line(boolean)])}
reg.check("QA-IOT-006", "FR-004", "Unknown sensor and boolean reading in a SAMPLE are rejected", "crafted SAMPLE payloads", "error and no sample queued",
          all(v.errors and not v.samples for v in t.values()), json.dumps({k: (err(v)[:1], len(v.samples)) for k, v in t.items()}, ensure_ascii=False))

# events: upload, missing chunk, corrupt hash, incomplete, duplicate, invalid window
upload = list(historical_device_messages())
starts = [m for m in upload if m["type"] == "EVENT_START"]
first_id = starts[0]["event_id"]
full = feed(upload)
n_full = len(full.events)
no_chunk = [m for m in upload if not (m["type"] == "EVENT_CHUNK" and m["event_id"] == first_id and m["payload"].get("chunk_index", m["payload"].get("index")) == 0)]
dropped = len(upload) - len(no_chunk)
nc = feed(no_chunk)
bad_hash = [mut(m, payload={**m["payload"], "sha256": "0" * 64}) if m["type"] == "EVENT_START" and m["event_id"] == first_id else m for m in upload]
bh = feed(bad_hash)
dupl = feed(upload + upload)
reg.check("QA-IOT-007", "IOT-003", "Historical event upload: valid assembly; missing chunk and wrong hash are not stored as events", "chunked upload of 2 events; drop first chunk of event 1; corrupt its SHA256",
          f"valid -> {n_full} events (expected 2); missing chunk -> fewer; bad hash -> fewer + error", n_full == 2 and dropped >= 1 and len(nc.events) < n_full and len(bh.events) < n_full and bool(bh.errors),
          f"valid={n_full} dropped_messages={dropped} missing_chunk={len(nc.events)} (errors {err(nc)[:1]}) bad_hash={len(bh.events)} (errors {err(bh)[:1]}) sent twice={len(dupl.events)} (DB de-duplicates, see QA-IOT-011)")
hist = historical_events()[0]
bad = hist.to_dict()
bad["end_ms"] = bad["trigger"]["timestamp_ms"] - 5000
try:
    Event.from_dict(bad)
    inv = "ACCEPTED"
except (ValueError, KeyError) as exc:
    inv = f"{type(exc).__name__}: {exc}"
reg.check("QA-IOT-008", "DATA-001", "Invalid event window (end before detection) is refused", "Event.from_dict with end_ms < trigger", "ValueError", inv != "ACCEPTED", inv[:120])

# protocol FILE source: backward timestamp, incomplete event, duplicate upload into the database
def write(name, msgs, raw_tail=b""):
    p = tmp / name
    p.write_bytes(b"".join(encode_message(m) for m in msgs) + raw_tail)
    return p


def run_file(p, name, fresh=True):
    db = tmp / f"{name}.sqlite3"
    for f in tmp.glob(f"{name}.sqlite3*") if fresh else ():
        f.unlink()
    out = {"error": None}
    with SQLiteRepository(db) as repo:
        src = ProtocolFileSource(p)
        s = Session(src, repo)
        try:
            s.start()
            while not src.exhausted:
                s.step()
            s.stop()
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass
        out.update(accepted=s.accepted, rejected=s.rejected, events=len(repo.list_events()), measurements=repo.connection.execute("select count(*) from measurements").fetchone()[0])
    return out


back = [mut(m) for m in base[:2]]
for i, m in enumerate(samples_only[:5]):
    mm = mut(m)
    mm["sequence_number"] = 2 + i
    ts = [0, 200, 400, 100, 600][i]
    mm["timestamp_ms"] = ts
    mm["payload"]["sample"]["timestamp_ms"] = ts
    back.append(mm)
res_back = run_file(write("backward.jsonl", back), "backward")
reg.check("QA-IOT-009", "FR-004", "Backward timestamp in a device stream is rejected by quality validation (counted, not stored)", "timestamps 0,200,400,100,600", "rejected >= 1, accepted 4",
          res_back["rejected"] >= 1 and res_back["accepted"] == 4, json.dumps(res_back))
head = [m for m in upload if m["type"] in ("HELLO", "CAPABILITIES")][:2]
trunc_msgs = head + [m for m in upload if m["type"] == "EVENT_START"][:1] + [m for m in upload if m["type"] == "EVENT_CHUNK"][:1]
res_trunc = run_file(write("truncated.jsonl", trunc_msgs), "truncated")
reg.check("QA-IOT-010", "IOT-003", "A protocol file that ends in the middle of an event upload is reported, no partial event stored", "EVENT_START + one chunk then EOF",
          "error 'Truncated' and 0 events", bool(res_trunc["error"]) and res_trunc["events"] == 0, json.dumps(res_trunc))
run_file(write("up1.jsonl", upload), "dupupload")
res_dup = run_file(write("up2.jsonl", upload), "dupupload", fresh=False)
res_same_stream = run_file(write("dup-same-stream.jsonl", upload + upload), "dupstream")
reg.check("QA-IOT-011", "IOT-003", "The same historical upload received in two separate connections stores each event once; replaying identical sequence numbers inside one stream is rejected loudly", "two sessions into one database; one stream with the upload twice", "2 events after the second connection; same-stream replay raises a protocol error", res_dup["events"] == 2 and not res_dup["error"] and bool(res_same_stream["error"]), json.dumps({"two_connections": res_dup, "same_stream_replay": res_same_stream}, ensure_ascii=False))
res_garbage = run_file(write("garbage.jsonl", base[:2], b"this is not json\n"), "garbage")
reg.check("QA-IOT-012", "FR-012", "Corrupted line in a protocol file ends with a clear protocol error", "valid handshake then garbage", "error reported", bool(res_garbage["error"]), json.dumps(res_garbage, ensure_ascii=False))


# ---------------------------------------------------------------------------- scripted TCP server
def server(chunks, hold=0.6, accept=1, pause=0.02):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)
    port = srv.getsockname()[1]

    def run():
        for _ in range(accept):
            try:
                c, _ = srv.accept()
            except OSError:
                return
            for ch in chunks:
                try:
                    c.sendall(ch)
                except OSError:
                    break
                time.sleep(pause)
            time.sleep(hold)
            c.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port


def drain(src, seconds=3.0):
    got, e = [], None
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            s = src.read_measurements()
            if s:
                got.append(s)
            else:
                time.sleep(0.003)
    except Exception as exc:  # noqa: BLE001
        e = exc
    return got, e


closed = socket.socket()
closed.bind(("127.0.0.1", 0))
free_port = closed.getsockname()[1]
closed.close()
try:
    NetworkDeviceSource(port=free_port).connect()
    refused = "CONNECTED"
except OSError as exc:
    refused = f"{type(exc).__name__}"
cfg = {}
for label, kw in {"LAN host": dict(host="192.168.1.5"), "hostname": dict(host="example.com"), "ipv6": dict(host="::1"), "port 0": dict(port=0), "port 70000": dict(port=70000), "timeout 0": dict(timeout=0), "reconnects 9": dict(max_reconnects=9)}.items():
    try:
        NetworkDeviceSource(**kw)
        cfg[label] = "ACCEPTED"
    except ValueError:
        cfg[label] = "rejected"
cfg["localhost"] = "accepted" if NetworkDeviceSource(host="localhost") else "?"
reg.check("QA-IOT-013", "CONN-001", "Closed port raises an OSError (refused/timeout); LAN/hostname/IPv6/invalid port/timeout/reconnect configs are rejected; localhost accepted",
          "closed port; 7 invalid constructor configs", "refused -> OSError; invalid -> ValueError", refused in ("ConnectionRefusedError", "TimeoutError") and all(v == "rejected" for k, v in cfg.items() if k != "localhost"),
          f"closed port -> {refused}; {cfg}")
good = [encode_message(m) for m in base]
p = server(good[:2] + [b"\xff\xfe not a protocol line\n"], hold=0.5)
src = NetworkDeviceSource(port=p, timeout=0.5, max_reconnects=0)
src.connect(); src.start()
got, e = drain(src, 2.5)
reg.check("QA-IOT-014", "FR-012", "Garbage after the handshake over TCP raises a protocol error to the application", "scripted server", "ValueError (protocol error)", isinstance(e, ValueError), f"error={e!r} samples={len(got)} state={src.state}")
src.disconnect()
p = server([], hold=2.0)
src = NetworkDeviceSource(port=p, timeout=0.3, max_reconnects=0)
t0 = time.monotonic()
src.connect(); src.start()
got, e = drain(src, 3.0)
reg.check("QA-IOT-015", "CONN-001", "A server that accepts but never sends: timeout leads to CONNECTION_LOST (no hang)", "silent server, timeout 0.3 s, no reconnects",
          "ConnectionError within ~1 s", isinstance(e, ConnectionError) and time.monotonic() - t0 < 2.5, f"error={e!r} state={src.state} after {time.monotonic() - t0:.2f}s")
src.disconnect()
p = server(good[:8], hold=0.0)
src = NetworkDeviceSource(port=p, timeout=0.3, max_reconnects=0)
src.connect(); src.start()
got, e = drain(src, 3.0)
reg.check("QA-IOT-016", "CONN-001", "Server closes the stream mid-data: samples already received are delivered, then CONNECTION_LOST",
          "HELLO, CAPS, samples then close", "some samples, then ConnectionError, state CONNECTION_LOST", bool(got) and isinstance(e, ConnectionError) and src.state == "CONNECTION_LOST",
          f"samples={len(got)} error={e!r} state={src.state}")
src.disconnect()
p = server([encode_message(base[0]), b"z" * 200_000], hold=0.3)
src = NetworkDeviceSource(port=p, timeout=0.5, max_reconnects=0)
src.connect(); src.start()
got, e = drain(src, 2.5)
reg.check("QA-IOT-017", "FR-012", "A 200 KB line without newline over TCP is rejected (bounded memory)", "oversized stream", "protocol error, receiver buffer bounded",
          e is not None and len(src.receiver.pending) <= 4096 + 8192, f"error={e!r} pending_bytes={len(src.receiver.pending)}")
src.disconnect()

# ---------------------------------------------------------------------------- fake serial: never writes, errors handled
class FakePort:
    def __init__(self, port=None, baudrate=None, timeout=None, write_timeout=None, script=(), fail_after=None):
        self.script, self.writes, self.fail_after, self.reads, self.closed = list(script), 0, fail_after, 0, False
        self.dtr = self.rts = None

    def open(self):
        pass

    def read(self, n):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            raise serial.SerialException("device unplugged")
        return self.script.pop(0) if self.script else b""

    def write(self, data):
        self.writes += 1
        raise AssertionError("the application wrote to the serial port")

    def close(self):
        self.closed = True


holder = {}


def factory(script, fail_after=None):
    def make(**kw):
        holder["port"] = FakePort(script=script, fail_after=fail_after, **kw)
        return holder["port"]

    return make


s_ok = SerialDeviceSource("COM_FAKE", factory([b"".join(good[:6])]))
s_ok.connect(); s_ok.start()
got_ok, e_ok = drain(s_ok, 1.0)
w_ok = holder["port"].writes
s_ok.disconnect()
s_unplug = SerialDeviceSource("COM_FAKE", factory([b"".join(good[:6])], fail_after=1))
s_unplug.connect(); s_unplug.start()
got_u, e_u = drain(s_unplug, 1.0)
s_unplug.disconnect()
s_bad = SerialDeviceSource("COM_FAKE", factory([good[0] + b"garbage line\n"]))
s_bad.connect(); s_bad.start()
got_b, e_b = drain(s_bad, 1.0)
s_bad.disconnect()
try:
    SerialDeviceSource("")
    empty = "ACCEPTED"
except ValueError:
    empty = "rejected"
try:
    SerialDeviceSource("socket://1.2.3.4:5")
    url = "ACCEPTED"
except ValueError:
    url = "rejected"
reg.check("QA-IOT-018", "SAF-001", "Serial (fake port): valid stream decoded; the app never writes to the port; unplug and garbage are reported; empty/URL ports refused",
          "FakePort with handshake+samples, unplug, garbage", "samples decoded, writes==0, ConnectionError on unplug, ValueError on garbage, port closed",
          len(got_ok) >= 3 and w_ok == 0 and isinstance(e_u, ConnectionError) and isinstance(e_b, ValueError) and empty == "rejected" and url == "rejected" and holder["port"].closed,
          f"decoded={len(got_ok)} writes={w_ok} unplug={e_u!r} garbage={e_b!r} empty={empty} url={url}",
          notes="Fake port only: no physical USB test (NOT TESTED on hardware).")
slow = SerialDeviceSource("COM_FAKE", factory([]))
slow.connect(); slow.start()
t0 = time.monotonic()
slow.connected_at -= 9.5  # shorten the documented 10 s handshake deadline without waiting 10 s
got_s, e_s = drain(slow, 2.0)
slow.disconnect()
reg.check("QA-IOT-019", "CONN-001", "No handshake within the documented 10 s raises TimeoutError and state TIMEOUT", "silent fake port (clock advanced 9.5 s)", "TimeoutError", isinstance(e_s, TimeoutError), f"{e_s!r}")


# ---------------------------------------------------------------------------- real loopback simulator (separate process)
def start_device(*extra):
    ready = tmp / f"ready-{time.monotonic_ns()}.json"
    proc = subprocess.Popen([sys.executable, "-m", "doctorcar.protocol.network_simulator", "--port", "0", "--speed", "100", "--history", str(tmp / "history.json"), "--ready", str(ready), *extra],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    end = time.monotonic() + 15
    while not ready.exists() and time.monotonic() < end:
        time.sleep(0.02)
    assert ready.exists(), proc.communicate(timeout=5)[1]
    return proc, json.loads(ready.read_text())["port"]


def session_run(db, port, target, extra_src=None):
    states = []
    with SQLiteRepository(db) as repo:
        src = NetworkDeviceSource(port=port, max_reconnects=1)
        s = Session(src, repo)
        s.start()
        end = time.monotonic() + 40
        try:
            while s.accepted < target and time.monotonic() < end:
                s.step()
                if not states or states[-1] != src.state:
                    states.append(src.state)
                time.sleep(0.0001)
        finally:
            s.stop()
        rows = repo.list_events()
        meas = repo.connection.execute("select session_id, count(*) from measurements group by session_id").fetchall()
        hist = [r for r in rows if r["origin"] == "HISTORICAL"]
        live = [r for r in rows if r["origin"] == "LIVE"]
        return {"accepted": s.accepted, "states": states, "historical": len(hist), "live": [r["kind"] for r in live], "sessions": [m[1] for m in meas], "info": src.get_device_info(), "reconnects": src.reconnects}


proc, port = start_device()
try:
    db = tmp / "e2e06.sqlite3"
    for f in tmp.glob("e2e06.sqlite3*"):
        f.unlink()
    r06 = session_run(db, port, 776)
finally:
    proc.terminate()
    proc.communicate(timeout=5)
reg.check("QA-E2E-006", "IOT-001/002", "Live loopback device: handshake, 776 samples, live event detected and stored, device info labelled as software/not a vehicle",
          "separate-process TCP simulator -> NetworkDeviceSource -> Session -> SQLite", "776 accepted; >=1 live non-quality event; info.vehicle_verified false; transport TCP_LOOPBACK",
          r06["accepted"] == 776 and any(k != "DATA_QUALITY" for k in r06["live"]) and r06["info"]["vehicle_verified"] is False and r06["info"]["transport"] == "TCP_LOOPBACK",
          json.dumps({k: v for k, v in r06.items() if k != "states"}, default=str) + f" states={r06['states']}")
proc, port = start_device()
try:
    db = tmp / "e2e07.sqlite3"
    for f in tmp.glob("e2e07.sqlite3*"):
        f.unlink()
    a = session_run(db, port, 776)
    proc.terminate()
    proc.communicate(timeout=5)
    proc, port = start_device()
    b = session_run(db, port, 776)
finally:
    proc.terminate()
    proc.communicate(timeout=5)
reg.check("QA-E2E-007", "IOT-003", "Device memory: 2 historical events imported once; reconnecting later does not duplicate them", "same device history, two live sessions into one database",
          "2 HISTORICAL events after both runs (not 4)", a["historical"] == 2 and b["historical"] == 2, f"first run historical={a['historical']}; second run total historical={b['historical']}")
proc, port = start_device("--disconnect-at-ms", "10000", "--max-connections", "2")
try:
    db = tmp / "e2e10.sqlite3"
    for f in tmp.glob("e2e10.sqlite3*"):
        f.unlink()
    r10 = session_run(db, port, 102)
finally:
    proc.terminate()
    proc.communicate(timeout=5)
reg.check("QA-E2E-010", "IOT-004", "Connection loss and reconnect: RECONNECTING shown, new boot isolated, no mixed sessions",
          "device drops at 10 s, then reconnects once", "RECONNECTING observed; reconnects==1; live samples split into two sessions of 51; historical events once",
          "RECONNECTING" in r10["states"] and r10["reconnects"] == 1 and sorted(x for x in r10["sessions"] if x < 100)[:2] == [51, 51] and r10["historical"] == 2,
          f"states={r10['states']} reconnects={r10['reconnects']} per-session sample counts={r10['sessions']} historical={r10['historical']}")
(folder / "iot-details.json").write_text(json.dumps({"e2e06": r06, "e2e07": [a, b], "e2e10": r10, "tcp_config": cfg}, ensure_ascii=False, indent=2, default=str), encoding="utf8")
reg.check("QA-IOT-020", "SAF-001", "Connecting to a loopback simulator is not evidence of a vehicle connection", "device info of the simulator session",
          "vehicle_verified false, transport TCP_LOOPBACK", r06["info"]["vehicle_verified"] is False and r06["info"]["transport"] == "TCP_LOOPBACK",
          f"vehicle_verified={r06['info']['vehicle_verified']} transport={r06['info']['transport']}", rel(folder / "iot-details.json"))
reg.save()
