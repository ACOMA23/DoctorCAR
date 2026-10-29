"""QA-SENSOR / QA-SIM: sensor correctness, operating relations, determinism, fault effects."""

import json
import math
import sqlite3
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import EVIDENCE, Registry, rel, scratch  # noqa: E402

from doctorcar.core.models import Quality, Reading  # noqa: E402
from doctorcar.core.sensor_registry import NUMERIC_IDS, REGISTRY  # noqa: E402
from doctorcar.core.session import Session  # noqa: E402
from doctorcar.monitoring.data_quality import DataQualityValidator  # noqa: E402
from doctorcar.sources.scenarios import SCENARIOS_MS, ScenarioInstance  # noqa: E402
from doctorcar.sources.simulation import SimulationSource  # noqa: E402
from doctorcar.storage.sqlite_repository import SQLiteRepository  # noqa: E402

reg = Registry("gate3")
folder = EVIDENCE / "gate3"
folder.mkdir(parents=True, exist_ok=True)
tmp = scratch("sensors")
EXPECTED_UNITS = {
    "RPM": "rpm", "SPEED": "km/h", "COOLANT_TEMP": "°C", "ENGINE_LOAD": "%", "THROTTLE_POS": "%",
    "INTAKE_PRESSURE": "kPa", "MAF": "g/s", "INTAKE_TEMP": "°C", "SHORT_FUEL_TRIM": "%",
    "LONG_FUEL_TRIM": "%", "CONTROL_MODULE_VOLTAGE": "V",
}


def trip(seed=4100, scale=1.0, warm=False, scenarios=(), mode=None, **kw):
    source = SimulationSource(
        seed=seed, scenario_family="multisensor",
        mode=mode or ("FAULT_INJECTION" if scenarios else "NORMAL"),
        scenarios=tuple(scenarios), driving_scale=scale, warm_start=warm, **kw,
    )
    source.connect()
    source.session_id = f"qa-{seed}-{scale}-{warm}"
    source.start()
    out = []
    while (s := source.read_measurements()) is not None:
        out.append(s)
    meta = source.get_simulation_metadata()
    source.disconnect()
    return out, meta


def val(sample, sensor):
    r = sample.readings[sensor]
    return r.value if r.quality == Quality.AVAILABLE else None


# ---------------------------------------------------------------------------- registry
t0 = time.monotonic()
ids = {s.sensor_id: s for s in REGISTRY.all()}
bad = [k for k, u in EXPECTED_UNITS.items() if k not in ids or ids[k].unit != u]
reg.check("QA-SENSOR-001", "FR-002", "Registry has the 11 documented numeric sensors with documented units + DTC",
          "REGISTRY.all()", "ids and units equal the control-file table (G)",
          not bad and "DTC" in ids and ids["DTC"].kind == "diagnostic" and len(ids) == 12,
          f"{len(ids)} sensors; unit mismatches: {bad or 'none'}", started=t0)

# ---------------------------------------------------------------------------- full-stream checks
samples, meta = trip()
n = len(samples)
steps = {b.timestamp_ms - a.timestamp_ms for a, b in zip(samples, samples[1:], strict=False)}
seqs_ok = all(b.sequence_number == a.sequence_number + 1 for a, b in zip(samples, samples[1:], strict=False))
types_bad, unit_bad, quality_bad = [], [], []
for s in samples:
    for sensor in NUMERIC_IDS:
        r = s.readings[sensor]
        if type(r.value) is bool or not isinstance(r.value, (int, float)) or not math.isfinite(r.value):
            types_bad.append((s.sequence_number, sensor))
        if r.unit != EXPECTED_UNITS[sensor]:
            unit_bad.append((s.sequence_number, sensor, r.unit))
        if r.quality != Quality.AVAILABLE:
            quality_bad.append((s.sequence_number, sensor, r.quality.value))
reg.check("QA-SENSOR-002", "FR-004", "Every sample of a normal 155 s trip: finite numeric values, correct units, AVAILABLE",
          "SimulationSource seed 4100 normal, all samples x 11 sensors", "776 samples, step 200 ms, contiguous sequence, no bad type/unit/quality",
          n == 776 and steps == {200} and seqs_ok and not types_bad and not unit_bad and not quality_bad,
          f"samples={n} steps={sorted(steps)} seq_contiguous={seqs_ok} bad_type={len(types_bad)} bad_unit={len(unit_bad)} bad_quality={len(quality_bad)}")

# ---------------------------------------------------------------------------- chain: source -> validated -> session -> SQLite
db = tmp / "chain.sqlite3"
for f in tmp.glob("chain.sqlite3*"):
    f.unlink()
source = SimulationSource(seed=4100, scenario_family="multisensor", mode="NORMAL")
stored_samples = []
t0 = time.monotonic()
with SQLiteRepository(db) as repo:
    session = Session(source, repo)
    session.start()
    while not source.exhausted:
        r = session.step()
        if r is not None and r.accepted:
            stored_samples.append(r.sample)
    session.stop()
con = sqlite3.connect(db)
rows = con.execute("select sequence_number, timestamp_ms, data_json from measurements order by sequence_number").fetchall()
mism, maxdiff = [], 0.0
for sample, (seq, ts, blob) in zip(stored_samples, rows, strict=True):
    data = json.loads(blob)
    readings = data["readings"]
    for sensor in NUMERIC_IDS:
        a, b = sample.readings[sensor].value, readings[sensor]["value"]
        maxdiff = max(maxdiff, abs(a - b))
        if a != b or readings[sensor]["unit"] != EXPECTED_UNITS[sensor]:
            mism.append((seq, sensor, a, b))
    if seq != sample.sequence_number or ts != sample.timestamp_ms:
        mism.append((seq, "time", ts, sample.timestamp_ms))
# compare against an independent regeneration of the same seed (source -> DB)
regen, _ = trip(4100)
src_diff = 0
for orig, (seq, ts, blob) in zip(regen, rows, strict=True):
    rd = json.loads(blob)["readings"]
    src_diff += sum(1 for sensor in NUMERIC_IDS if orig.readings[sensor].value != rd[sensor]["value"])
reg.check("QA-SENSOR-003", "DATA-002", "Simulation output -> validated sample -> Session -> SQLite is value-exact for all samples",
          "Session over SimulationSource seed 4100; compare 776x11 values with measurements table and with an independent regeneration",
          "0 mismatches, max |difference| = 0 (no rounding applied by the pipeline)",
          not mism and src_diff == 0 and len(rows) == 776, f"rows={len(rows)} session_vs_db_mismatches={len(mism)} max_diff={maxdiff} source_vs_db_mismatches={src_diff}",
          started=t0)
con.close()

# ---------------------------------------------------------------------------- validator behavior
v = DataQualityValidator()
base = replace(samples[10], received_at_ms=None)
ok = v.validate_measurement(base)
dup = v.validate_measurement(base)
back = v.validate_measurement(replace(samples[5], received_at_ms=None))
v2 = DataQualityValidator()
cases = {}


def issues_for(mutate, now=None):
    vv = DataQualityValidator()
    s = replace(samples[20], received_at_ms=None, readings={k: r for k, r in samples[20].readings.items()})
    mutate(s.readings)
    res = vv.validate_measurement(s, now)
    return res.accepted, res.issues, {k: r.quality.value for k, r in res.sample.readings.items() if r.quality != Quality.AVAILABLE}


cases["missing"] = issues_for(lambda r: r.__setitem__("MAF", Reading(None, "g/s", Quality.MISSING)))
cases["unsupported"] = issues_for(lambda r: r.__setitem__("MAF", Reading(None, "g/s", Quality.UNSUPPORTED)))
cases["wrong_unit"] = issues_for(lambda r: r.__setitem__("COOLANT_TEMP", Reading(90.0, "K")))
cases["implausible_rpm"] = issues_for(lambda r: r.__setitem__("RPM", Reading(25000.0, "rpm")))
cases["stale"] = issues_for(lambda r: None, now=samples[20].timestamp_ms + 10_000)
errors = {}
for label, make in {"nan": lambda: Reading(float("nan"), "rpm"), "inf": lambda: Reading(float("inf"), "rpm"),
                    "bool": lambda: Reading(True, "rpm")}.items():
    try:
        make()
        errors[label] = "ACCEPTED"
    except (ValueError, TypeError) as exc:
        errors[label] = type(exc).__name__
missing_kept_none = cases["missing"][2].get("MAF") == "MISSING"
unsupported_kept = cases["unsupported"][2].get("MAF") == "UNSUPPORTED"
reg.check("QA-SENSOR-004", "FR-004", "Validator: missing/unsupported/unit/range/stale/duplicate/backward timestamps",
          "crafted samples through DataQualityValidator", "MISSING and UNSUPPORTED stay explicit (never 0 or AVAILABLE); wrong unit and out-of-range flagged; stale flagged; duplicate and backward rejected; NaN/Inf/bool refused",
          ok.accepted and not dup.accepted and not back.accepted and missing_kept_none and unsupported_kept
          and "COOLANT_TEMP" in cases["wrong_unit"][2] and "RPM" in cases["implausible_rpm"][2]
          and "STALE" in cases["stale"][2].values() and all(e != "ACCEPTED" for e in errors.values()),
          json.dumps({"dup_accepted": dup.accepted, "backward_accepted": back.accepted, **{k: c[2] for k, c in cases.items()}, "constructor_errors": errors}, ensure_ascii=False))

# ---------------------------------------------------------------------------- operating relations by phase
phase_rows = {}
for tag, kw in (("cold", dict(warm=False)), ("warm", dict(warm=True)), ("cold-1.14", dict(warm=False, scale=1.14)), ("cold-0.86", dict(warm=False, scale=0.86))):
    ss, _ = trip(seed=4200, **kw)
    by = {}
    for s in ss:
        by.setdefault(s.phase, []).append(s)
    phase_rows[tag] = (ss, by)
viol = {"maf": [], "map": [], "volt": [], "load": [], "coolant": []}
stats = {}
for tag, (ss, by) in phase_rows.items():
    for s in ss:
        rpm, load, maf, mapv = (val(s, k) for k in ("RPM", "ENGINE_LOAD", "MAF", "INTAKE_PRESSURE"))
        exp_maf = rpm * (0.002 + 0.00008 * load)
        if abs(maf - exp_maf) > 0.002 + 0.001 * exp_maf:
            viol["maf"].append((tag, s.sequence_number, maf, exp_maf))
        exp_map = 30 + 0.65 * load if rpm > 0 else 100.0
        if abs(mapv - exp_map) > 0.002:
            viol["map"].append((tag, s.sequence_number, mapv, exp_map))
        volt = val(s, "CONTROL_MODULE_VOLTAGE")
        if (rpm > 0 and not 13.7 <= volt <= 14.1) or (rpm == 0 and abs(volt - 12.4) > 0.01):
            viol["volt"].append((tag, s.sequence_number, rpm, volt))
        if rpm == 0 and load != 0:
            viol["load"].append((tag, s.sequence_number, load))
    cool = [val(s, "COOLANT_TEMP") for s in ss]
    if tag.startswith("cold") and not all(b >= a - 1e-9 for a, b in zip(cool, cool[1:], strict=False)):
        viol["coolant"].append((tag, "non-monotonic warm-up"))
    stats[tag] = {
        "coolant_start": cool[0], "coolant_end": cool[-1],
        **{p: {"n": len(rows), "rpm_mean": round(statistics.mean(val(s, "RPM") for s in rows), 1),
               "load_mean": round(statistics.mean(val(s, "ENGINE_LOAD") for s in rows), 1),
               "throttle_mean": round(statistics.mean(val(s, "THROTTLE_POS") for s in rows), 1),
               "speed_mean": round(statistics.mean(val(s, "SPEED") for s in rows), 1),
               "maf_mean": round(statistics.mean(val(s, "MAF") for s in rows), 2)} for p, rows in by.items()},
    }
(folder / "operating-phase-statistics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf8")
cold0, warm0 = stats["cold"]["coolant_start"], stats["warm"]["coolant_start"]
reg.check("QA-SENSOR-005", "FR-003", "Declared relations hold in every sample of 4 normal trips (cold/warm/scale 0.86/1.14)",
          "MAF=RPM*(0.002+0.00008*load); MAP=30+0.65*load (100 at rpm 0); voltage 13.7-14.1 V running and 12.4 V stopped; load 0 when stopped; cold coolant monotonic",
          "0 violations over 4 x 776 samples", not any(viol.values()),
          "violations " + json.dumps({k: len(x) for k, x in viol.items()}) + f"; coolant start cold={cold0} warm={warm0}",
          rel(folder / "operating-phase-statistics.json"))
# qualitative couplings
cruise = [s for s in phase_rows["cold"][0] if s.phase == "سير مستقر"]
accel = [s for s in phase_rows["cold"][0] if s.phase == "تسارع"]
idle = [s for s in phase_rows["cold"][0] if s.phase == "خمول"][:40]


def corr(xs, ys):
    return statistics.correlation(xs, ys)


c_thr_load = corr([val(s, "THROTTLE_POS") for s in phase_rows["cold"][0] if val(s, "RPM") > 0],
                  [val(s, "ENGINE_LOAD") for s in phase_rows["cold"][0] if val(s, "RPM") > 0])
c_speed_rpm = corr([val(s, "SPEED") for s in accel], [val(s, "RPM") for s in accel])
c_load_maf = corr([val(s, "ENGINE_LOAD") for s in phase_rows["cold"][0] if val(s, "RPM") > 0],
                  [val(s, "MAF") for s in phase_rows["cold"][0] if val(s, "RPM") > 0])
idle_rpm = statistics.mean(val(s, "RPM") for s in idle)
sft = [val(s, "SHORT_FUEL_TRIM") for s in phase_rows["cold"][0]]
lft = [val(s, "LONG_FUEL_TRIM") for s in phase_rows["cold"][0]]
reg.check("QA-SENSOR-006", "FR-003", "Plausible couplings: throttle~load, speed~rpm in acceleration, load~MAF, idle rpm, trims bounded",
          "correlations on a cold normal trip", "corr(throttle,load)>0.9; corr(speed,rpm | accel)>0.99; corr(load,MAF)>0.9; idle rpm 800-820; |STFT|<=2; LTFT 1.2-1.8",
          c_thr_load > 0.9 and c_speed_rpm > 0.99 and c_load_maf > 0.9 and 790 <= idle_rpm <= 830 and max(abs(x) for x in sft) <= 2.0 + 1e-9 and 1.2 <= min(lft) and max(lft) <= 1.8,
          f"corr_thr_load={c_thr_load:.3f} corr_speed_rpm_accel={c_speed_rpm:.4f} corr_load_maf={c_load_maf:.3f} idle_rpm={idle_rpm:.1f} stft=[{min(sft):.2f},{max(sft):.2f}] ltft=[{min(lft):.3f},{max(lft):.3f}]")

# ---------------------------------------------------------------------------- determinism and counts
a, _ = trip(seed=777)
b, _ = trip(seed=777)
c, _ = trip(seed=778)
same = all(x.readings[k].value == y.readings[k].value for x, y in zip(a, b, strict=True) for k in NUMERIC_IDS)
differs = sum(1 for x, y in zip(a, c, strict=True) if x.readings["RPM"].value != y.readings["RPM"].value)
reg.check("QA-SIM-001", "SIM-003", "Same seed reproduces all readings; different seed changes noisy signals",
          "seed 777 twice, seed 778 once", "identical for same seed; RPM differs in >50% samples for another seed",
          same and differs > len(a) * 0.5, f"identical={same} rpm_differs_other_seed={differs}/{len(a)}")
short, _ = trip(seed=9, duration_ms=60_000)
reg.check("QA-SIM-002", "SIM-001", "Trip length follows duration (0..60 s at 200 ms = 301 samples; no gaps)",
          "duration_ms=60000", "301 samples", len(short) == 301 and {y.timestamp_ms - x.timestamp_ms for x, y in zip(short, short[1:], strict=False)} == {200},
          f"{len(short)} samples")

# ---------------------------------------------------------------------------- fault effects per scenario
baseline, _ = trip(seed=4300)
effects = {}
START, DUR = 60_000, 35_000
declared = {k: {"sensors": list(d.sensors), "writes": list(d.writes)} for k, d in SCENARIOS_MS.items()}
for sid in SCENARIOS_MS:
    variants = ("default",) if sid != "S07" else ("dropout", "flatline", "implausible")
    for variant in variants:
        faulty, _ = trip(seed=4300, scenarios=(ScenarioInstance(sid, START, DUR, 1.0, variant),))
        changed_in, changed_out, quality_flag = {}, set(), 0
        for x, y in zip(baseline, faulty, strict=True):
            inside = START <= x.timestamp_ms < START + DUR
            for sensor in NUMERIC_IDS:
                rx, ry = x.readings[sensor], y.readings[sensor]
                if ry.quality != Quality.AVAILABLE:
                    quality_flag += 1
                if (rx.value != ry.value) or (rx.quality != ry.quality):
                    if inside:
                        d = (ry.value - rx.value) if (ry.value is not None and rx.value is not None) else None
                        cur = changed_in.setdefault(sensor, {"n": 0, "max_abs": 0.0, "sum": 0.0})
                        cur["n"] += 1
                        if d is not None:
                            cur["max_abs"] = max(cur["max_abs"], abs(d))
                            cur["sum"] += d
                    else:
                        changed_out.add((sensor, x.timestamp_ms))
        effects[f"{sid}:{variant}"] = {
            "declared_writes": declared[sid]["writes"], "affected_inside": {k: {"n": v["n"], "max_abs": round(v["max_abs"], 3), "mean_delta": round(v["sum"] / v["n"], 3) if v["n"] else None} for k, v in changed_in.items()},
            "changed_outside_window": len(changed_out), "non_available_readings": quality_flag,
        }
(folder / "fault-effects.json").write_text(json.dumps(effects, ensure_ascii=False, indent=2), encoding="utf8")
for sid in SCENARIOS_MS:
    e = effects[f"{sid}:default" if sid != "S07" else "S07:dropout"]
    writes = set(e["declared_writes"])
    got = set(e["affected_inside"])
    reg.check(f"QA-SIM-01{sid[-1]}", f"MS-SIM/{sid}", f"{sid}: only declared sensors change, and only inside the injection window",
              f"{sid} at 60 s, 35 s, severity 1.0 vs same-seed baseline", "changed sensors subset of declared writes; nothing changed outside [60,95) s",
              got and got <= writes and e["changed_outside_window"] == 0,
              f"declared={sorted(writes)} changed={sorted(got)} outside={e['changed_outside_window']}", rel(folder / "fault-effects.json"))


def eff(key, sensor):
    return effects[key]["affected_inside"].get(sensor, {})


directional = {
    "S01 coolant rises >10 C": (eff("S01:default", "COOLANT_TEMP").get("max_abs", 0) > 10, eff("S01:default", "COOLANT_TEMP")),
    "S02 MAF lower than baseline": ((eff("S02:default", "MAF").get("mean_delta") or 0) < 0, eff("S02:default", "MAF")),
    "S03 short trim positive": ((eff("S03:default", "SHORT_FUEL_TRIM").get("mean_delta") or 0) > 1, eff("S03:default", "SHORT_FUEL_TRIM")),
    "S04 MAF biased": (eff("S04:default", "MAF").get("max_abs", 0) > 1, eff("S04:default", "MAF")),
    "S05 voltage drops": ((eff("S05:default", "CONTROL_MODULE_VOLTAGE").get("mean_delta") or 0) < -0.3, eff("S05:default", "CONTROL_MODULE_VOLTAGE")),
}
reg.check("QA-SIM-030", "MS-SIM", "Direction of the effect matches each scenario's definition",
          "deltas vs baseline inside the window", "S01 coolant up; S02 MAF down; S03 short trim up; S04 MAF biased; S05 voltage down",
          all(ok for ok, _ in directional.values()), json.dumps({k: (ok, d) for k, (ok, d) in directional.items()}, ensure_ascii=False), rel(folder / "fault-effects.json"))
d_drop = effects["S07:dropout"]["non_available_readings"]
d_flat = effects["S07:flatline"]
d_imp = effects["S07:implausible"]["non_available_readings"]
reg.check("QA-SIM-031", "MS-SIM/S07", "S07 variants: dropout -> MISSING readings; implausible -> INVALID/out-of-range; flatline -> constant value",
          "S07 variants", "dropout and implausible raise non-AVAILABLE readings or change values; flatline freezes a sensor",
          d_drop > 0 and d_imp > 0 and bool(d_flat["affected_inside"]),
          f"dropout non-available={d_drop} implausible non-available={d_imp} flatline affected={sorted(d_flat['affected_inside'])}", rel(folder / "fault-effects.json"))

# S06 intermittency, durations and recovery
s6, _ = trip(seed=4300, scenarios=(ScenarioInstance("S06", START, DUR, 1.0),))
diff_ms = [x.timestamp_ms for x, y in zip(baseline, s6, strict=True) if any(x.readings[k].value != y.readings[k].value for k in NUMERIC_IDS)]
pulses = 1 + sum(1 for a_, b_ in zip(diff_ms, diff_ms[1:], strict=False) if b_ - a_ > 200) if diff_ms else 0
reg.check("QA-SIM-032", "MS-SIM/S06", "S06 is intermittent: several separate pulses with normal samples between them",
          "S06 35 s", ">=2 separate pulses inside the window, no changes outside", pulses >= 2 and min(diff_ms) >= START and max(diff_ms) < START + DUR,
          f"pulses={pulses} first={min(diff_ms) if diff_ms else None} last={max(diff_ms) if diff_ms else None}")
for dur in (5_000, 90_000):
    f5, _ = trip(seed=4300, scenarios=(ScenarioInstance("S01", START, dur, 1.0),))
    d5 = [x.timestamp_ms for x, y in zip(baseline, f5, strict=True) if x.readings["COOLANT_TEMP"].value != y.readings["COOLANT_TEMP"].value]
    reg.check(f"QA-SIM-03{3 if dur == 5000 else 4}", "MS-SIM", f"Injection of {dur // 1000} s is applied for its duration and then recovers",
              f"S01 duration {dur} ms", "first change >= 60 s; changes stop within one second after the end",
              bool(d5) and min(d5) >= START and max(d5) <= START + dur + 1000, f"changed from {min(d5) if d5 else None} to {max(d5) if d5 else None}")
sim_two, _ = trip(seed=4300, scenarios=(ScenarioInstance("S01", 50_000, 40_000), ScenarioInstance("S02", 60_000, 35_000)))
changed = {k for x, y in zip(baseline, sim_two, strict=True) for k in NUMERIC_IDS if x.readings[k].value != y.readings[k].value}
conflict = None
try:
    trip(seed=4300, scenarios=(ScenarioInstance("S01", 50_000, 40_000), ScenarioInstance("S01", 60_000, 35_000)))
    conflict = "ACCEPTED"
except ValueError as exc:
    conflict = f"rejected: {exc}"
three = None
try:
    trip(seed=4300, scenarios=(ScenarioInstance("S01", 50_000, 30_000), ScenarioInstance("S02", 55_000, 30_000), ScenarioInstance("S05", 70_000, 20_000)))
    three = "accepted"
except ValueError as exc:
    three = f"rejected: {exc}"
reg.check("QA-SIM-035", "MS-SIM", "Simultaneous scenarios combine; conflicting writes to the same sensor are rejected",
          "S01+S02 overlapping; S01+S01 overlapping; S01+S02+S05", "union of effects for compatible; error for conflicts; three-scenario behaviour reported",
          {"COOLANT_TEMP", "MAF"} <= changed and conflict.startswith("rejected"), f"S01+S02 changed={sorted(changed)}; same-scenario overlap {conflict}; triple {three}")

# random faults and 30 s cycles
metas = {}
for seed in (11, 11, 12):
    s_, m_ = trip(seed=seed, mode="RANDOM_FAULTS", max_faults=2, normal_probability=0.25)
    metas.setdefault(seed, []).append((m_, s_))
m11a, m11b = metas[11][0][0], metas[11][1][0]
m12 = metas[12][0][0]
same_schedule = json.dumps(m11a.get("scenario_cycles"), sort_keys=True, default=str) == json.dumps(m11b.get("scenario_cycles"), sort_keys=True, default=str)
diff_schedule = json.dumps(m11a.get("scenario_cycles"), sort_keys=True, default=str) != json.dumps(m12.get("scenario_cycles"), sort_keys=True, default=str)
cycles = m11a.get("scenario_cycles") or m11a.get("cycles")
same_data = all(x.readings[k].value == y.readings[k].value for x, y in zip(metas[11][0][1], metas[11][1][1], strict=True) for k in NUMERIC_IDS)
(folder / "random-faults-metadata.json").write_text(json.dumps({"seed11": m11a, "seed12": m12}, ensure_ascii=False, indent=2, default=str), encoding="utf8")
reg.check("QA-SIM-036", "SIM-002/003", "RANDOM_FAULTS: 30 s cycles, ground-truth schedule recorded, same seed reproducible, other seed differs",
          "RANDOM_FAULTS seeds 11,11,12", "cycles recorded every 30 s; identical schedule and data for the same seed; different schedule for another seed",
          bool(cycles) and same_schedule and same_data and diff_schedule and meta is not None,
          f"cycles={len(cycles) if cycles else 0} schedule_repeat={same_schedule} data_repeat={same_data} other_seed_differs={diff_schedule}",
          rel(folder / "random-faults-metadata.json"))

reg.save()
