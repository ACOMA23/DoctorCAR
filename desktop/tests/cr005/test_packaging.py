"""Gate 7: the model ships with the package and the pinned dependencies match its metadata."""

import tomllib
from pathlib import Path

from doctorcar.analysis.model import MODEL_V1, MODEL_V2, MODELS_ROOT, AnomalyModel, available_models

ROOT = Path(__file__).resolve().parents[3]


def pins(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text("utf8").splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==")
            result[name.strip().lower()] = version.strip()
    return result


def test_package_data_and_extras_cover_the_artifacts():
    config = tomllib.loads((ROOT / "desktop" / "pyproject.toml").read_text("utf8"))
    data = config["tool"]["setuptools"]["package-data"]["doctorcar"]
    assert "analysis/models/*/model.joblib" in data and "analysis/models/*/metadata.json" in data
    assert all(
        (MODELS_ROOT / name / f).is_file()
        for name in (MODEL_V1, MODEL_V2)
        for f in ("model.joblib", "metadata.json")
    )
    assert set(available_models()) == {MODEL_V1, MODEL_V2, "cr006-iforest-v3"}
    extras = config["project"]["optional-dependencies"]
    assert {d.split("==")[0] for d in extras["ml"]} == {"numpy", "scikit-learn", "joblib"}
    assert extras["train"] == ["pandas==3.1.0"]


def test_lock_file_pins_every_ml_dependency_to_the_versions_models_were_trained_with():
    locked = pins(ROOT / "desktop" / "requirements-lock.txt")
    config = tomllib.loads((ROOT / "desktop" / "pyproject.toml").read_text("utf8"))
    for requirement in config["project"]["optional-dependencies"]["ml"]:
        name, version = requirement.split("==")
        assert locked[name] == version
    for name in (MODEL_V1, MODEL_V2):
        meta = AnomalyModel(name).metadata
        assert locked["scikit-learn"] == meta["sklearn_version"]
        assert locked["numpy"] == meta["numpy_version"]
    assert {"scipy", "threadpoolctl"} <= set(locked)
