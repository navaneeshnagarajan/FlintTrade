"""Producer readback binds full durable custody receipts, not ACK references."""
from __future__ import annotations

from typing import Any

import pytest

from packages.core.core.tests.test_native_custody_owner import _preview, _selection
from packages.core.core.tests.test_native_financial_owner import RUN, _qualify
from packages.core.core.tests.test_native_model_producer_v2 import model_desk, response
from packages.core.core.tests.test_native_model_safety_v2 import _option_plan
from packages.core.core.tests.test_native_producer_v2 import _plan
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("options", [False, True], ids=["cash", "options"])
def test_complete_receipt_readback_preserves_current_and_historical_acceptance(
    mounted_desk: MountedDesk, options: bool,
) -> None:
    """The ordinary exact-run GET corroborates every field without another fetch.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        options: Whether the synthetic run uses the nominal options rather than cash profile.
    """
    desk = mounted_desk
    source, registration = model_desk(desk, response, options=options)
    (_option_plan if options else _plan)(source, registration, mark="5")
    selected = _selection(_qualify(desk))
    selected["limits"]["instruments"] = [{
        "instrument_id": registration.order["symbol"], "exchange": registration.order["exchange"],
        "product": registration.order["product"],
    }]
    preview = _preview(desk, selected)
    acknowledgement = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    }, headers=desk.headers)
    assert acknowledgement.status_code == 200, acknowledgement.get_json()
    receipt = acknowledgement.get_json()["data"]
    readback = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
    assert readback.status_code == 200, readback.get_json()
    view = readback.get_json()["data"]
    assert view.get("transfer_receipts") == [receipt]
    assert view["duty"]["receiving_acceptance_ref"] == receipt["transfer_ref"]
    # A newly observed synthetic cash fill or option duty makes old acceptance
    # historical, not current. The complete accepted payload must remain.
    from packages.core.core.tests.test_native_financial_owner import _cash_filled, _facts

    facts: dict[str, Any] = _facts()
    if not options:
        _cash_filled(facts, mark="4")
    else:
        # Canonical commands are not manufactured to force an options obligation.
        facts["tariff_ref"] = None
    source.publish("mounted-native", facts)
    _qualify(desk)
    later = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
    assert later.status_code == 200, later.get_json()
    historical = later.get_json()["data"]
    assert historical["transfer_receipts"] == [receipt]
    assert historical["effective_authority"] == "none"
    if not options:
        assert historical["duty"]["receiving_acceptance_ref"] is None
        from packages.core.core.tests.test_native_financial_owner import _settle_cash

        _settle_cash(desk, source, facts)
    assert desk.calls == []
