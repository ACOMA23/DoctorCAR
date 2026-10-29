"""DC-FIX-001 Gate 5: DEF-001/002 ML is advisory; v3 is the conservative default."""

import pytest

from doctorcar.analysis.analyzer import AnomalyAnalyzer
from doctorcar.analysis.model import (
    DEFAULT_MODEL,
    MODEL_V1,
    MODEL_V3,
    AnomalyModel,
    available_models,
)
from doctorcar.core.session import Session
from doctorcar.sources.simulation import SimulationSource
from doctorcar.storage.sqlite_repository import SQLiteRepository


def run(tmp_path, ml_alerts, model_name=MODEL_V1, seed=15001, scale=1.12):
    source = SimulationSource(
        seed=seed, scenario_family="multisensor", mode="NORMAL", driving_scale=scale
    )
    with SQLiteRepository(tmp_path / f"ml-{ml_alerts}.sqlite3") as repo:
        session = Session(
            source, repo, analyzer=AnomalyAnalyzer(AnomalyModel(model_name)), ml_alerts=ml_alerts
        )
        session.start()
        while not source.exhausted:
            session.step()
        session.stop()
        kinds = [r["kind"] for r in repo.list_events()]
    return kinds, session


def test_v3_is_packaged_default_and_loads():
    assert DEFAULT_MODEL == MODEL_V3 and MODEL_V3 in available_models()
    meta = AnomalyModel(MODEL_V3).metadata
    assert meta["model_version"] == "iforest-cr006-v3"
    assert set(meta["train_trips"]).isdisjoint(meta["validation_trips"])
    assert all(int(t.split("-")[1]) >= 12000 for t in meta["train_trips"])  # new seed range only


def test_ml_only_anomaly_opens_an_event_only_when_ml_alerts_are_enabled(tmp_path):
    with_alerts, _ = run(tmp_path, True)
    assert (
        "ML_ANOMALY" in with_alerts
    )  # v1 on a cold, high-scale normal trip (DEF-002 reproduction)
    advisory, session = run(tmp_path, False)
    assert "ML_ANOMALY" not in advisory
    assert advisory == []  # nothing else opened on a healthy trip
    assert session.advisory_ml  # the opinion is kept, not discarded


@pytest.mark.parametrize("seed", [15000, 15004])
def test_default_model_is_quiet_on_cold_high_scale_trips(tmp_path, seed):
    kinds, _ = run(tmp_path, True, MODEL_V3, seed=seed, scale=1.12)
    assert "ML_ANOMALY" not in kinds
