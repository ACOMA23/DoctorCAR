"""Only locally trained, pinned and hash-checked artifacts shipped in the package are loadable."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from doctorcar.analysis.windows import FEATURE_NAMES, SCHEMA_VERSION

MODELS_ROOT = Path(__file__).resolve().parent / "models"
MODEL_V1 = "cr004-iforest-v1"
MODEL_V2 = "cr005-iforest-v2"
MODEL_V3 = "cr006-iforest-v3"  # default since DC-FIX-001
# The application default. DC-CR-005 records why this value was chosen in the control file.
DEFAULT_MODEL = MODEL_V3
# Trust anchor outside the artifact directory: replacing model and metadata together is refused.
TRUSTED_SHA256 = {
    MODEL_V1: "0970cd008d891a014bbcf26a08f85e2fd30bae1e495a1ec9cbb2b3a6caa197a7",
    MODEL_V2: "03153e0da6e1fc2bd87bc1f3b19598bdbb82a0da1bc893cbd8a7ffb9bfd85d87",
    MODEL_V3: "aae2f3ccc379335c4cde52ef001c6b68826b98a58fd6cd18b9e8043bb3bd3057",
}
DEFAULT_POLICY = {"consecutive": 3, "hysteresis": 0.02}
MODEL_DIR = MODELS_ROOT / DEFAULT_MODEL  # compatibility alias for the default artifact


class ModelLoadError(RuntimeError):
    """The model could not be loaded; the message names the exact reason."""


def available_models() -> tuple[str, ...]:
    if not MODELS_ROOT.is_dir():
        return ()
    return tuple(sorted(p.name for p in MODELS_ROOT.iterdir() if (p / "metadata.json").is_file()))


class AnomalyModel:
    def __init__(self, name: str | None = None) -> None:
        name = name or DEFAULT_MODEL
        if name not in available_models():
            raise ModelLoadError(f"Unknown model '{name}'; packaged: {available_models()}")
        directory = MODELS_ROOT / name
        try:
            import joblib
            import numpy as np  # noqa: F401
            import sklearn
        except ImportError as exc:
            raise ModelLoadError(
                f"ML dependencies are not installed ({exc.name}); install doctorcar[ml]"
            ) from exc
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf8"))
        path = directory / "model.joblib"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != meta["sha256"] or (name in TRUSTED_SHA256 and digest != TRUSTED_SHA256[name]):
            raise ModelLoadError(f"Model integrity check failed for {name}")
        if meta["feature_schema"] != SCHEMA_VERSION or meta["feature_names"] != list(FEATURE_NAMES):
            raise ModelLoadError(f"Feature schema mismatch for {name}")
        if meta["sklearn_version"] != sklearn.__version__:
            raise ModelLoadError(
                f"scikit-learn {sklearn.__version__} installed but {name} was trained with "
                f"{meta['sklearn_version']}; install the pinned version from requirements-lock.txt"
            )
        # No API accepts an external joblib path. The packaged directory is a trusted artifact.
        self.pipeline = joblib.load(path)
        self.metadata: dict[str, Any] = meta
        self.name = name

    @property
    def policy(self) -> dict[str, Any]:
        return {**DEFAULT_POLICY, **self.metadata.get("detection_policy", {})}

    def scores(self, rows: Any) -> Any:
        import numpy as np

        # sklearn score_samples is lower for anomalies; expose a larger-is-unusual score.
        return -self.pipeline.score_samples(np.asarray(rows, dtype=float))

    def infer(self, window: dict[str, Any]) -> dict[str, Any]:
        if window["decision"] != "READY":
            return dict(window)
        if window["feature_names"] != self.metadata["feature_names"]:
            raise ValueError("Feature order mismatch")
        started = time.perf_counter()
        score = float(self.scores([window["features"]])[0])
        threshold = float(self.metadata["threshold"])
        return {
            **window,
            "decision": "ANOMALOUS" if score > threshold else "NORMAL",
            "score": score,
            "threshold": threshold,
            "model_version": self.metadata["model_version"],
            "model_sha256": self.metadata["sha256"],
            "inference_ms": (time.perf_counter() - started) * 1000,
        }
