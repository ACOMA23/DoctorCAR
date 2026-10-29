"""Diagnostic: time AnomalyAnalyzer() construction per model in a fresh process (read-only use of shipped models)."""
import sys, time
t0 = time.perf_counter()
from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.model import AnomalyModel, MODEL_V1, MODEL_V2, MODEL_V3, DEFAULT_MODEL
t1 = time.perf_counter()
print("import", round(t1 - t0, 2), "default", DEFAULT_MODEL)
for name in (DEFAULT_MODEL, MODEL_V2, MODEL_V1, DEFAULT_MODEL):
    a = time.perf_counter(); AnomalyModel(name); b = time.perf_counter()
    print(name, "load_s", round(b - a, 2))
a = time.perf_counter(); AnomalyAnalyzer(); print("AnomalyAnalyzer() default", round(time.perf_counter() - a, 2))
