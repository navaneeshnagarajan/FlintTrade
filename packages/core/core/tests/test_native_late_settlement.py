"""Late canonical evidence after terminal settlement, with explicit process loss.

The child exercises the original normal-factory/installed-SDK positive first.
A held result is never translated into successful fixture cleanup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from packages.core.core.tests.native_terminal_variants import TERMINAL_VARIANTS
from packages.core.core.tests.native_writer_fixture import mounted_desk as mounted_desk
from packages.core.core.tests.test_laya_qualification_owner import sidecar as sidecar
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk

pytestmark = pytest.mark.integration


def _retained_command_json(app: Any) -> str:
    """Read exact persisted command bytes without rewriting settlement history."""
    with app.config["EXECUTION_SESSIONS"].autonomy.db.transaction() as db:
        return db.execute("SELECT data FROM commands WHERE run_id=? AND command_id=?",
                          ("mounted-native", "decision-0")).fetchone()[0]


def _retained_command(app: Any) -> dict[str, Any]:
    """Supplement public duty/drain assertions with read-only retained history."""
    return json.loads(_retained_command_json(app))


def _child(case: str, output: Path) -> None:
    """Run one unchanged public lifecycle and exit only after its held-state witness."""
    class Observe:
        """Attach only a test callback after the actual terminal positive."""

        def pytest_runtest_setup(self, item: Any) -> None:
            """Delegate the original body, fixtures and five-second worker wait."""
            original = item.module._terminal_lifecycle_case

            def observe(desk: Any, capture: Any) -> None:
                """Require late evidence to remain owed while finance is unavailable."""
                from packages.core.core.tests.test_native_financial_owner import RUN, _financial
                before = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
                original_bytes = _retained_command_json(desk.app)
                original_command = json.loads(original_bytes)
                repeated = capture("identical-terminal")
                assert _retained_command_json(desk.app) == original_bytes
                assert repeated["duty"]["obligations"] == []
                assert repeated["entry_state"] == "retired"
                assert desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
                late = capture(case)
                from flinttrade_core.broker_identity import BrokerSelector
                ledger = desk.app.extensions["flinttrade_broker_dependencies"].lifecycle_store
                snapshot = ledger.observation_snapshot(BrokerSelector("dhan", "Mounted"))
                payload = json.loads(snapshot.evidence_json)
                canonical = {"payload": payload, "surfaces": {
                    item.surface: json.loads(item.value_json) if item.value_json is not None else None
                    for item in snapshot.surfaces}, "conflicts": snapshot.conflicts}
                if case in TERMINAL_VARIANTS and TERMINAL_VARIANTS[case][3] is not None:
                    prior = original_command["settlement_v2"]["observation"]
                    records = json.loads(payload["native_scope_json"])["records"]
                    ack = [entry for entry in ledger.native_dispatch_evidence(prior["attempt_id"])
                           if entry["kind"] == "acknowledged"][0]
                    current, origin = records[0], ack["native_scope_observation"]
                    assert {k: v for k, v in current.items() if k != "resources"} == {
                        k: v for k, v in origin.items() if k != "resources"}
                    assert [{k: v for k, v in resource.items() if k != "filled_quantity"}
                            for resource in current["resources"]] == [
                        {k: v for k, v in resource.items() if k != "filled_quantity"}
                        for resource in origin["resources"]]
                    rows = canonical["surfaces"]["orders"]
                    assert len(rows) == 1
                    assert (rows[0]["orderid"], rows[0]["broker_account_id"], rows[0]["exchange_order_id"],
                            rows[0]["broker_exchange_segment"]) == (
                        "synthetic-canonical-order", "Mounted", "ExchangeOne", "NSE_EQ")
                    assert not snapshot.conflicts
                if case == "price-conflict":
                    row = canonical["surfaces"]["orders"][0]
                    assert row["price"] == "5" and row["quantity"] == "1" and row["filled_quantity"] == "0"
                    assert row["status"] == "CANCELLED" and row["pricetype"] == "LIMIT" and row["action"] == "BUY"
                    assert (row["symbol"], row["broker_account_id"], row["exchange_order_id"]) == (
                        "SYNTH", "Mounted", "ExchangeOne")
                    prior = original_command["settlement_v2"]["observation"]
                    records = json.loads(payload["native_scope_json"])["records"]
                    assert len(records) == 1 and records[0]["resources"] == prior["resources"]
                    assert records[0]["resources"][0]["native_order_date"] == "2026-10-23"
                    ack = [entry for entry in ledger.native_dispatch_evidence(prior["attempt_id"])
                           if entry["kind"] == "acknowledged"][0]
                    assert records[0] == ack["native_scope_observation"]
                    assert not snapshot.conflicts
                finance = _financial(desk)
                drained = desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
                result = {"case": case, "before": before, "repeated": repeated, "late": late,
                          "financial": finance, "drained": drained, "canonical": canonical,
                          "workspace": str(desk.app.extensions["flinttrade_broker_dependencies"].workspace_path),
                          "provenance": "synthetic-installed-SDK-held-state-before-explicit-process-loss"}
                output.write_text(json.dumps(result))
                assert finance["assessment"]["status"] == "unavailable"
                held = case in {"late-fill", "late-conflict", "zero-fill-conflict"} or (
                    case in TERMINAL_VARIANTS and TERMINAL_VARIANTS[case][3] is not None)
                command = _retained_command(desk.app)
                result["command"] = command
                raw_response = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
                result["http"] = {"method": "GET", "path": RUN + "/autonomy-v2",
                                  "status": raw_response.status_code, "body": raw_response.get_data(as_text=True)}
                if held:
                    assert late["duty"]["obligations"] and not drained, "new exact-resource liability was lost"
                    expected_fill = (TERMINAL_VARIANTS[case][2] if case in TERMINAL_VARIANTS
                                     else 0 if case == "zero-fill-conflict" else 1)
                    assert command["filled_quantity"] == expected_fill
                    assert "settled" in command["events"]
                    assert command["settlement_v2"]["cause"] == "bounded_terminal_zero_fill_financially_settled"
                    assert late["duty"]["obligation_revision"] != before["duty"]["obligation_revision"]
                    missing = capture("missing-child-set")
                    assert missing["duty"]["obligations"]
                    assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
                    retained = _retained_command(desk.app)
                    assert retained["filled_quantity"] == expected_fill
                    assert retained["late_evidence_v2"] == command["late_evidence_v2"]
                    if case in TERMINAL_VARIANTS:
                        conflict = command["late_evidence_v2"]
                        assert conflict["conflicting"] and not conflict["zero_fill_terminal"]
                        assert TERMINAL_VARIANTS[case][3] in conflict["conflicts"]
                        if case == "native-fill-conflict":
                            assert "cumulative_resource_fill_mismatch" in conflict["conflicts"]
                        replay = capture("identical-terminal")
                        assert replay["duty"]["obligations"]
                        assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
                        assert _retained_command(desk.app)["late_evidence_v2"] == conflict
                    if case == "zero-fill-conflict":
                        conflict = command["late_evidence_v2"]
                        assert conflict["conflicting"] and conflict["conflict"] == "signed_quantity_mismatch"
                        assert conflict["observed_quantity"] == 2 and conflict["signed_quantity"] == 1
                        assert conflict["filled_quantity"] == 0 and not conflict["zero_fill_terminal"]
                        replay = capture("identical-terminal")
                        assert replay["duty"]["obligations"]
                        assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
                        assert _retained_command(desk.app)["late_evidence_v2"] == command["late_evidence_v2"]
                else:
                    assert command == original_command
                output.write_text(json.dumps(result))
                assert bool(late["duty"]["obligations"]) is held, result
                assert drained is not held, result
                assert late["entry_state"] == "retired" and late["grant"]["state"] == "revoked"
                if not held:
                    return  # Ordinary successful finalizers must still run.
                # No finalizer suppression or forced release. The child now
                # models process loss with durable liabilities still held.
                os._exit(0)

            def extended(*args: Any, **kwargs: Any) -> None:
                """Forward the original lifecycle with the explicit after-settlement observer."""
                original(*args, **kwargs, after_settlement=observe)

            item.module._terminal_lifecycle_case = extended

    code = pytest.main(["-c", "pyproject.toml", "--rootdir", ".",
                        "packages/core/core/tests/test_native_order_safety_v2.py::"
                        "test_qualified_normal_factory_producer_reaches_the_canonical_sdk",
                        "--import-mode=importlib", "-q", "-o", "cache_dir=" + str(output.parent / "child-cache"),
                        "--randomly-seed=3029168366"], plugins=[Observe()])
    raise SystemExit(code or (0 if output.exists() else 97))


def _restart(output: Path) -> None:
    """Reacquire the exited child's real workspace and prove durable held custody."""
    from flinttrade_core import app as app_module, auth_state
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from packages.core.core.tests.test_native_financial_owner import RUN

    witness = json.loads(output.read_text())
    root = Path(witness["workspace"])
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(root)
    app_module._MASTER_PASSWORD = "pytest-master-password"
    auth_state.reset_singleton_for_tests()
    auth_state.get_auth_state(db_path=root / "late-restart-auth.sqlite")
    lease = acquire_backend_instance_lease()
    app = app_module.create_flask_app(backend_lease_proof=lease.proof)
    app.config["TESTING"] = True
    with app.app_context():
        token = _create_token("mounted-operator", mode="live", live_mode_unlocked=True)
    client = app.test_client()
    headers = {"Authorization": "Bearer " + token}
    response = client.get(RUN + "/autonomy-v2", headers=headers)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()["data"]
    command = _retained_command(app)
    assert body["duty"]["obligations"] and body["entry_state"] == "retired"
    assert body["grant"]["state"] == "revoked"
    assert command["filled_quantity"] == witness["command"]["filled_quantity"]
    assert command["settlement_v2"] == witness["command"]["settlement_v2"]
    assert command["late_evidence_v2"] == witness["command"]["late_evidence_v2"]
    assert not app.config["EXECUTION_SESSIONS"].shutdown(0)
    evidence = {"view": body, "command": command, "drained": False,
                "http": {"method": "GET", "path": RUN + "/autonomy-v2", "status": response.status_code,
                         "body": response.get_data(as_text=True)},
                "disposition": "observed held-state followed by explicit second process loss"}
    output.with_name("restart.json").write_text(json.dumps(evidence))
    os._exit(0)


@pytest.mark.parametrize("case", ["late-fill", "late-conflict", "late-date", "foreign-account", "missing-child-set",
                                 "zero-fill-conflict",
                                 *(case for case, variant in TERMINAL_VARIANTS.items() if variant[3] is not None)])
def test_late_bounded_evidence_retains_duty_after_zero_fill_settlement(tmp_path: Path, case: str) -> None:
    """A later sealed observation cannot disappear behind a stale financial publication."""
    result_path = tmp_path / "late-evidence.json"
    code = ("from pathlib import Path\n"
            "from packages.core.core.tests.test_native_late_settlement import _child\n"
            f"_child({case!r}, Path({str(result_path)!r}))\n")
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=40)
    (tmp_path / "child.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    witness = json.loads(result_path.read_text())
    held = case in {"late-fill", "late-conflict", "zero-fill-conflict"} or (
                    case in TERMINAL_VARIANTS and TERMINAL_VARIANTS[case][3] is not None)
    assert witness["drained"] is not held
    assert bool(witness["late"]["duty"]["obligations"]) is held
    if held:
        restart_code = ("from pathlib import Path\n"
                        "from packages.core.core.tests.test_native_late_settlement import _restart\n"
                        f"_restart(Path({str(result_path)!r}))\n")
        restarted = subprocess.run([sys.executable, "-B", "-c", restart_code],
                                   capture_output=True, text=True, timeout=20)
        (tmp_path / "restart.log").write_text(restarted.stdout + restarted.stderr)
        assert restarted.returncode == 0, restarted.stdout + restarted.stderr
        assert json.loads(result_path.with_name("restart.json").read_text())["drained"] is False


def test_benign_and_unattributable_terminal_variants_preserve_settlement(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Check the benign matrix without sharing any held contradiction state.

    Each observation must leave the original persisted settlement byte-identical.
    The ordinary normal-factory finalizers still run; no process loss is needed
    for these no-duty controls. Contradictions retain separate fresh processes.
    """
    from packages.core.core.tests.test_native_order_safety_v2 import _terminal_lifecycle_case
    from packages.core.core.tests.test_native_financial_owner import _financial

    witnesses: list[dict[str, Any]] = []

    def observe(desk: MountedDesk, capture: Any) -> None:
        """Inspect each external benign/identity-negative row with unchanged authority."""
        original = _retained_command_json(desk.app)
        ledger = desk.app.extensions["flinttrade_broker_dependencies"].lifecycle_store
        classify = ledger.native_command_observation
        classifications: list[dict[str, Any]] = []

        def observe_classification(*args: Any, **kwargs: Any) -> dict[str, Any]:
            """Forward the real owner and distinguish benign evidence from refusal."""
            try:
                evidence = classify(*args, **kwargs)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                classifications.append({"unavailable": True})
                raise
            classifications.append({"evidence": evidence})
            return evidence

        monkeypatch.setattr(ledger, "native_command_observation", observe_classification)
        for case, variant in TERMINAL_VARIANTS.items():
            if variant[3] is not None:
                continue
            start = len(classifications)
            view = capture(case)
            current = classifications[start:]
            assert len(current) == 1
            if case.startswith("equivalent-") or case == "ignored-inactive-fields":
                assert current[0]["evidence"]["zero_fill_terminal"]
                assert not current[0]["evidence"].get("conflicting", False)
            else:
                assert current == [{"unavailable": True}]
            finance = _financial(desk)
            drained = desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
            assert _retained_command_json(desk.app) == original
            assert view["duty"]["obligations"] == [] and drained
            assert view["entry_state"] == "retired" and view["grant"]["state"] == "revoked"
            assert finance["assessment"]["status"] == "unavailable"
            witnesses.append({"case": case, "view": view, "financial": finance, "drained": drained,
                              "canonical_classification": current})
            (tmp_path / "benign-evidence.json").write_text(json.dumps(witnesses))

    _terminal_lifecycle_case(mounted_desk, sidecar, monkeypatch, after_settlement=observe)
    assert [item["case"] for item in witnesses] == [
        case for case, variant in TERMINAL_VARIANTS.items() if variant[3] is None]
