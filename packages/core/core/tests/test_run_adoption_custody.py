"""Established model evidence must never silently restart with empty history."""
from __future__ import annotations

import os
import sqlite3

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("kind", ["evaluation", "adoption", "training"])
def test_model_authority_database_loss_refuses_reconstruction(tmp_path, kind):
    from flinttrade_core.evaluation import EvaluationStore
    from flinttrade_core.artifact_activation import ArtifactActivation
    from flinttrade_core.training_jobs import TrainingJobs
    path = tmp_path / (kind + ".sqlite")
    def create():
        if kind == "evaluation":
            return EvaluationStore(path)
        if kind == "adoption":
            return ArtifactActivation(path, runs=None, serving=None, authority=None, qualification=None)
        return TrainingJobs(path, None)
    create()
    assert path.stat().st_mode & 0o777 == 0o600
    path.unlink()
    with pytest.raises((ValueError, RuntimeError, OSError, sqlite3.DatabaseError)):
        create()
    assert not path.exists(), "missing established authority must not be recreated"


def test_evaluation_rejects_existing_symlink_and_lost_table(tmp_path):
    from flinttrade_core.evaluation import EvaluationStore
    path = tmp_path / "evaluation.sqlite"
    EvaluationStore(path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE accesses")
    with pytest.raises((ValueError, RuntimeError, sqlite3.DatabaseError)):
        EvaluationStore(path)
    alias = tmp_path / "alias.sqlite"
    os.symlink(path, alias)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        EvaluationStore(alias)
