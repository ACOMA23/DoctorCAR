"""Shared QA harness: result registry with explicit pass criteria and evidence paths.

QA scripts never modify product code. Every PASS needs an actual, recorded observation.
"""

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = (
    Path(os.environ["QA_EVIDENCE"])
    if os.environ.get("QA_EVIDENCE")
    else ROOT / "docs" / "evidence" / "full-qa"
)
STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT TESTED", "PARTIAL")


def scratch(name: str) -> Path:
    base = Path(os.environ.get("QA_TMP", tempfile.gettempdir())) / "doctorcar-qa" / name
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Case:
    test_id: str
    requirement: str
    title: str
    input: str
    expected: str
    actual: str
    status: str
    evidence: str = ""
    duration_s: float | None = None
    notes: str = ""


@dataclass
class Registry:
    gate: str
    environment: dict[str, Any] = field(default_factory=dict)
    cases: list[Case] = field(default_factory=list)
    defects: list[dict[str, Any]] = field(default_factory=list)

    def add(self, *args: Any, **kwargs: Any) -> Case:
        case = Case(*args, **kwargs)
        assert case.status in STATUSES, case.status
        self.cases.append(case)
        marker = {"PASS": "ok", "FAIL": "FAIL", "PARTIAL": "part", "BLOCKED": "BLOCK", "NOT TESTED": "n/t"}
        print(f"[{marker[case.status]:5s}] {case.test_id}: {case.title} -> {case.actual[:140]}", flush=True)
        return case

    def check(
        self,
        test_id: str,
        requirement: str,
        title: str,
        input_: str,
        expected: str,
        ok: bool,
        actual: str,
        evidence: str = "",
        notes: str = "",
        started: float | None = None,
    ) -> Case:
        return self.add(
            test_id,
            requirement,
            title,
            input_,
            expected,
            actual,
            "PASS" if ok else "FAIL",
            evidence,
            round(time.monotonic() - started, 2) if started else None,
            notes,
        )

    def defect(self, defect_id: str, severity: str, requirement: str, title: str, steps: str,
               expected: str, actual: str, evidence: str, cause: str, impact: str, fix: str) -> None:
        self.defects.append(
            {
                "id": defect_id, "severity": severity, "requirement": requirement, "title": title,
                "steps": steps, "expected": expected, "actual": actual, "evidence": evidence,
                "suspected_root_cause": cause, "impact": impact, "suggested_fix": fix, "status": "OPEN",
            }
        )
        print(f"[DEFECT] {defect_id} {severity}: {title}", flush=True)

    def save(self) -> Path:
        folder = EVIDENCE / self.gate
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "results.json"
        path.write_text(
            json.dumps(
                {"gate": self.gate, "environment": self.environment,
                 "cases": [asdict(c) for c in self.cases], "defects": self.defects},
                ensure_ascii=False, indent=2, default=str,
            ),
            encoding="utf8",
        )
        counts = {s: sum(1 for c in self.cases if c.status == s) for s in STATUSES}
        print(f"== {self.gate}: {counts}; defects={len(self.defects)} -> {path}", flush=True)
        return path


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")
