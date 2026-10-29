"""Aggregate every results.json of docs/evidence/post-remediation-qa into ALL_CASES.md / CASE_SUMMARY.json (read-only on results)."""

import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "post-remediation-qa"
final_gates = ["gate2", "gate2_controls", "gui_ext", "gui_xai", "integration", "ai_reports", "gate3", "gate4", "gate7", "gate8", "gate9", "gate10", "gate10b"]
rows, summary = [], {}
for g in final_gates:
    p = root / g / "results.json"
    if not p.exists():
        summary[g] = "missing"
        continue
    d = json.loads(p.read_text("utf8"))
    summary[g] = dict(Counter(c["status"] for c in d["cases"]))
    rows.extend((g, c) for c in d["cases"])
total = Counter(c["status"] for _, c in rows)
superseded = {}
for p in sorted(root.glob("**/results-run*.json")) + [root / "gate2_run1" / "results.json"]:
    if p.exists():
        superseded[str(p.relative_to(root)).replace("\\", "/")] = dict(Counter(c["status"] for c in json.loads(p.read_text("utf8"))["cases"]))
(root / "CASE_SUMMARY.json").write_text(
    json.dumps({"final": summary, "total": dict(total), "cases": len(rows), "superseded_runs": superseded}, ensure_ascii=False, indent=2), encoding="utf8")


def esc(text):
    return str(text).replace("|", "/").replace("\n", " ")[:260]


out = ["# All recorded cases (final runs) - expected vs actual", "", f"Total {len(rows)} cases: {dict(total)}", "",
       "| Gate | ID | Title | Input | Expected | Actual | Status |", "| --- | --- | --- | --- | --- | --- | --- |"]
for g, c in rows:
    out.append(f"| {g} | {c['test_id']} | {esc(c['title'])} | {esc(c['input'])} | {esc(c['expected'])} | {esc(c['actual'])} | **{c['status']}** |")
(root / "ALL_CASES.md").write_text("\n".join(out), encoding="utf8")
print(json.dumps({"total": dict(total), "cases": len(rows)}))
