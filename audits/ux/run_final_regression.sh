#!/bin/bash
# DC-UX-001 final regression chain (native GUI scripts need the desktop; pytest runs offscreen)
cd /c/doccar
L=docs/evidence/ui-ux-redesign/regression
export PYTHONIOENCODING=utf-8 PYTHONPATH=C:/doccar/desktop/src QA_EVIDENCE="C:/doccar/docs/evidence/ui-ux-redesign/regression" QA_TMP="$(cygpath -w "$TEMP")"
echo "start $(date +%T)" > $L/final-chain.log
QT_QPA_PLATFORM=offscreen timeout 1500 .venv/Scripts/python.exe -m pytest -c desktop/pyproject.toml desktop/tests audits/test_m1_acceptance.py -p no:cacheprovider --basetemp="$(cygpath -w "$TEMP")/dc-ux-final" --junitxml=$L/pytest-full.xml -q > $L/pytest-full.log 2>&1; echo "pytest exit=$? $(date +%T)" >> $L/final-chain.log
.venv/Scripts/python.exe -m ruff check desktop/src desktop/tests > $L/lint.log 2>&1; .venv/Scripts/python.exe -m ruff format --check desktop/src desktop/tests >> $L/lint.log 2>&1; .venv/Scripts/python.exe -m mypy desktop/src --config-file desktop/pyproject.toml >> $L/lint.log 2>&1; .venv/Scripts/python.exe -m pip check >> $L/lint.log 2>&1; echo "lint done $(date +%T)" >> $L/final-chain.log
for s in "audits/post_remediation/pr_gui.py" "audits/ux/ux_gui_controls.py" "audits/post_remediation/pr_gui_ext.py" "audits/post_remediation/pr_e2e.py" "audits/post_remediation/pr_gui_xai.py"; do
  n=$(basename $s .py)
  timeout 900 .venv/Scripts/python.exe -B $s > $L/final-run-$n.log 2>&1; echo "$n exit=$? $(date +%T)" >> $L/final-chain.log
done
echo "done $(date +%T)" >> $L/final-chain.log
