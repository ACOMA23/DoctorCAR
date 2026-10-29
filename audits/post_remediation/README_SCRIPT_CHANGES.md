# DC-VERIFY-002 script changes (copies of audits/qa; originals untouched)
- pr_gui.py = qa_gui.py; only change: shared `qa_common` is imported from `audits/qa` (path line).
- pr_gui_controls.py = qa_gui_controls.py; changes (both are the QA-SCRIPT errors adjudicated in docs/evidence/full-qa/adjudication.json):
  1. QA-UI-039: Replay wait 60 s -> 150 s (Replay plays in recorded real time; detection is at 68.2 s).
  2. QA-UI-041: pass criterion accepts the localized stage name "تصل البيانات" as well as "RECEIVING".
- No product code was changed. Evidence goes to docs/evidence/post-remediation-qa via QA_EVIDENCE.
- pr_e2e.py = qa_e2e.py; QA-E2E-009 criterion/title: the expected model version string `iforest-cr005-v2` -> `iforest-cr006-v3` (default model changed by DC-FIX-001 Gate 5; the check itself - XAI line + model version in technical report - is unchanged).
- pr_integration.py, pr_ai.py, pr_gui_ext.py are NEW scripts (DC-VERIFY-002). Corrections made to them before their recorded runs (own-script errors, not product): pr_integration QA-REG-007 expects PARTIAL (not COMPLETE) for events whose T+30 s is beyond the 155 s trip end; QA-REG-008 uses a 9 s fault (5-6 s faults are below the documented detection gate); QA-REG-010 split into finite (010) and non-finite (010b) cases because the first NaN rejects the whole file. pr_ai QA-V3-008: the ANOMALOUS-only gate is in Session, not in explain(); the check moved to stored analyses (008b). First-run logs are kept as *-run1.* files.
- Originals under audits/qa and docs/evidence/full-qa were not modified.
