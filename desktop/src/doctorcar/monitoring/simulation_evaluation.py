"""Post-hoc test evaluation. No ground truth is passed to the detector or reports."""

from typing import Any

from doctorcar.core.models import Event
from doctorcar.sources.faults import FAULTS


def compare_schedule(
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    now_ms: int,
    event_details: dict[str, Event] | None = None,
) -> dict[str, Any]:
    if metadata.get("scenario_family") == "multisensor":
        return compare_scenarios(metadata, events, now_ms, event_details or {})
    results = []
    matched: set[str] = set()
    for index, fault in enumerate(metadata["fault_schedule"]):
        definition = FAULTS[fault["fault_id"]]
        matches = [
            e
            for e in events
            if e["kind"] in definition.detected_by
            and fault["start_ms"] <= e["trigger_ms"] < fault["start_ms"] + fault["duration_ms"]
        ]
        matched.update(e["event_id"] for e in matches)
        status = (
            "NOT_STARTED"
            if now_ms < fault["start_ms"]
            else "DETECTED"
            if matches
            else "PENDING"
            if now_ms < fault["start_ms"] + fault["duration_ms"]
            else "NOT_DETECTED"
        )
        results.append(
            {
                "index": index,
                **fault,
                "status": status,
                "detectable_in_m1": definition.detectable_in_m1,
                "event_ids": [e["event_id"] for e in matches],
            }
        )
    return {
        "faults": results,
        "unmatched_events": [e["event_id"] for e in events if e["event_id"] not in matched],
        "seed": metadata["seed"],
        "cycles": metadata["cycles"],
        "schedule_version": metadata["schedule_version"],
    }


def compare_scenarios(
    metadata: dict[str, Any], events: list[dict[str, Any]], now_ms: int, details: dict[str, Event]
) -> dict[str, Any]:
    """Post-hoc temporal pattern agreement, never a mechanical correctness score."""
    from doctorcar.diagnostics.evidence import build_evidence
    from doctorcar.diagnostics.hypotheses import evaluate_hypotheses
    from doctorcar.monitoring.evidence_rules import WINDOW_MS

    expected = {
        "S01": "MS_THERMAL",
        "S02": "MS_AIR_FUEL",
        "S03": "MS_FUEL_RESPONSE",
        "S04": "MS_AIRFLOW",
        "S05": "MS_SUPPLY",
        "S06": "MS_COMBUSTION",
        "S07": "MS_SIGNAL",
    }
    results = []
    matched: set[str] = set()
    schedule = metadata["scenario_schedule"]
    for index, instance in enumerate(schedule):
        candidates = [
            e
            for e in events
            if e["kind"] == expected[instance["scenario_id"]]
            and instance["start_ms"]
            <= e["trigger_ms"]
            < instance["start_ms"] + instance["duration_ms"] + WINDOW_MS
        ]
        selected = []
        for candidate in candidates:
            event = details.get(candidate["event_id"])
            if event and any(
                f.rule_id == candidate["kind"] and len(f.metrics) >= 3
                for f in build_evidence(event).findings
            ):
                selected.append(candidate)
        matched.update(e["event_id"] for e in selected)
        patterns = []
        for row in selected:
            event = details.get(row["event_id"])
            if event:
                evidence = build_evidence(event)
                hypotheses = evaluate_hypotheses(event, evidence)
                patterns.append(
                    {
                        "event_id": event.event_id,
                        "pattern": event.trigger.kind,
                        "hypotheses": [h.description for h in hypotheses],
                        "evidence": list(event.trigger.evidence),
                        "checks": [h.recommended_check for h in hypotheses],
                    }
                )
        status = (
            "NOT_STARTED"
            if now_ms < instance["start_ms"]
            else "PATTERN_DETECTED"
            if selected
            else "CENSORED"
            if now_ms >= metadata["duration_ms"]
            and now_ms < instance["start_ms"] + instance["duration_ms"] + WINDOW_MS
            else "PENDING"
            if now_ms < instance["start_ms"] + instance["duration_ms"] + WINDOW_MS
            else "NOT_DETECTED"
        )
        results.append(
            {
                "index": index,
                **instance,
                "fault_id": instance["scenario_id"],
                "status": status,
                "detectable_in_m1": True,
                "event_ids": [e["event_id"] for e in selected],
                "unverified_event_ids": [e["event_id"] for e in candidates if e not in selected],
                "detections": patterns,
            }
        )
    unmatched = [e for e in events if e["kind"].startswith("MS_") and e["event_id"] not in matched]
    outside = [
        e["event_id"]
        for e in unmatched
        if not any(
            i["start_ms"] <= e["trigger_ms"] < i["start_ms"] + i["duration_ms"] + WINDOW_MS
            for i in schedule
        )
    ]
    return {
        "faults": results,
        "unmatched_events": [e["event_id"] for e in unmatched],
        "false_positive_events_on_known_normal": outside,
        "auxiliary_quality_events": [e["event_id"] for e in events if e["kind"] == "DATA_QUALITY"],
        "seed": metadata["seed"],
        "cycles": metadata["scenario_cycles"],
        "schedule_version": metadata["scenario_version"],
        "causal_diagnostic_accuracy": "NOT_MEASURED",
    }
