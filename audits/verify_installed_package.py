import json
from pathlib import Path

import doctorcar
from doctorcar.analysis import model as m
from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.sources.scenarios import ScenarioInstance
from doctorcar.sources.simulation import SimulationSource

pkg = Path(doctorcar.__file__).resolve()
out = {
    "package_file": str(pkg),
    "from_site_packages": "site-packages" in str(pkg),
    "models_root": str(m.MODELS_ROOT),
    "available": list(m.available_models()),
    "default": m.DEFAULT_MODEL,
}
for name in m.available_models():
    out[name] = m.AnomalyModel(name).metadata["sha256"]
src = SimulationSource(
    seed=4100,
    scenario_family="multisensor",
    mode="FAULT_INJECTION",
    scenarios=(ScenarioInstance("S02", 60000, 35000),),
)
src.connect()
src.start()
analyzer = AnomalyAnalyzer()
scores, triggers = [], []
while (s := src.read_measurements()) is not None:
    r, t = analyzer.push(s)
    if r is not None and "score" in r:
        scores.append(round(r["score"], 9))
    if t:
        triggers.append(t.timestamp_ms)
out.update(
    model_version=analyzer.model.metadata["model_version"],
    windows_scored=len(scores),
    score_sum=round(sum(scores), 6),
    triggers=triggers,
    cwd=str(Path.cwd()),
)
print(json.dumps(out, indent=2))
