#!/bin/bash
# Re-runs the unmodified campaign scripts that do not need a visible window; logs next to the evidence.
cd /c/doccar
export QA_EVIDENCE="C:/doccar/docs/evidence/post-remediation-qa" PYTHONIOENCODING=utf-8 PYTHONPATH=C:/doccar/desktop/src
L=docs/evidence/post-remediation-qa
for s in qa_sensors_sim qa_events_db qa_masking qa_iot; do
  echo "### $s $(date +%T)" >> $L/chain.log
  timeout 1500 .venv/Scripts/python.exe -B audits/qa/$s.py > $L/run-$s.log 2>&1; echo "$s exit=$?" >> $L/chain.log
done
echo "### done $(date +%T)" >> $L/chain.log
