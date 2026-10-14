"""Explicit imported/manual evidence never becomes a broker book."""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest
from flask import Flask

pytestmark = pytest.mark.integration


def test_import_manual_deduplication_and_exact_account_readback(tmp_path):
    import flinttrade_data
    assert (Path(flinttrade_data.__file__).parent / "portfolio_evidence.py").exists(), "portfolio evidence seam missing"
    module = importlib.import_module("flinttrade_data.portfolio_evidence")
    from flinttrade_historical.local_data_routes import local_data_bp
    path = tmp_path / "owned-test-ledger.sqlite"
    connection = sqlite3.connect(path)
    owner = module.PortfolioEvidence(connection)
    scope = {"principal_id": "test", "environment": "research", "account_id": "imported-test",
             "run_id": None, "generation": 1}
    app = Flask(__name__)
    app.config.update(DATA_SCOPE_RESOLVER=lambda: scope, PORTFOLIO_EVIDENCE_OWNER=owner,
                      DATA_EVIDENCE_WRITE_ALLOWED=lambda: True)
    app.register_blueprint(local_data_bp)
    client = app.test_client()
    csv = "\n".join((
        "record_id,kind,instrument_id,venue,currency,quantity_unit,quantity,observed_at",
        "row-1,holding,synthetic-scheme,AMFI,INR,units,0.125,2026-01-01T00:00:00+00:00",
        "",
    ))
    payload = {"origin": "statement_csv", "source_id": "user-statement", "csv": csv}
    first = client.post("/api/v1/data/portfolio/evidence", json=payload)
    assert first.status_code == 201
    assert client.post("/api/v1/data/portfolio/evidence", json=payload).json == first.json
    record = {"record_id": "manual-1", "kind": "transaction", "instrument_id": "synthetic-scheme", "venue": "AMFI",
              "currency": "INR", "quantity_unit": "units", "quantity": "0.25", "cash_amount": "-10.25",
              "observed_at": "2026-01-02T00:00:00+00:00"}
    assert client.post("/api/v1/data/portfolio/evidence", json={"origin": "manual", "source_id": "manual",
                                                             "records": [record]}).status_code == 201
    evidence = client.get("/api/v1/data/portfolio/evidence").json["data"]
    assert evidence["complete"] is False and evidence["execution_authority"] is False
    assert len(evidence["records"]) == 2
    assert evidence["records"][0]["quantity"] == "0.125"
    assert evidence["records"][0]["cash_amount"] is None
    assert evidence["records"][1]["origin"] == "manual"
    assert evidence["holdings_inferred_from_transactions"] is False
    changed = csv.replace("0.125", "0.5")
    assert client.post("/api/v1/data/portfolio/evidence", json={**payload, "csv": changed}).status_code == 409
    assert len(owner.read(scope)["records"]) == 2
    assert owner.read({**scope, "account_id": "other"})["records"] == []
    connection.close()
    reopened = sqlite3.connect(path)
    assert len(module.PortfolioEvidence(reopened).read(scope)["records"]) == 2
    reopened.close()


def test_evidence_does_not_commit_another_owners_transaction_or_accept_corruption(tmp_path):
    from flinttrade_data.portfolio_evidence import PortfolioEvidence
    connection = sqlite3.connect(tmp_path / "owned.sqlite")
    connection.execute("CREATE TABLE other_work (value INTEGER)")
    connection.execute("INSERT INTO other_work VALUES (1)")
    with pytest.raises(RuntimeError):
        PortfolioEvidence(connection)
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM other_work").fetchone()[0] == 0
    owner = PortfolioEvidence(connection)
    scope = {"principal_id": "test", "environment": "research", "account_id": "imported-test",
             "run_id": None, "generation": 1}
    record = {"record_id": "test", "kind": "holding", "instrument_id": "synthetic-scheme", "venue": "AMFI",
              "currency": "INR", "quantity_unit": "units", "quantity": "1.5",
              "observed_at": "2026-01-01T00:00:00+00:00"}
    owner.append(scope=scope, origin="manual", source_id="manual", records=[record])
    connection.execute("UPDATE portfolio_evidence SET document='{}'")
    connection.commit()
    with pytest.raises(ValueError):
        owner.read(scope)
    assert connection.execute("SELECT document FROM portfolio_evidence").fetchone()[0] == "{}"
    connection.close()
