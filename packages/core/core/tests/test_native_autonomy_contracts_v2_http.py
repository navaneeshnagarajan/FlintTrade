"""The transport-only foundation must not mount or activate a v2 route."""
import pytest

from .test_native_autonomy import CONFIG, URL
from .test_native_autonomy import desk as desk


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient

pytestmark = pytest.mark.integration


def test_current_public_owner_still_refuses_unmounted_v2_and_keeps_v1(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Retain legacy configuration while refusing versioned input at the legacy owner.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, _other = desk
    assert client.post("/api/v2/execution-sessions/native", json=CONFIG, headers=headers).status_code == 404
    created = client.post(URL + "/native", json=CONFIG, headers=headers)
    assert created.status_code == 201
    row = created.json["data"]
    assert row["configured"] is True
    assert row["qualified"] is False and row["authorised"] is False
    assert row["commands"] == []
    assert client.post(URL + "/bounded-one/autonomy/qualify", headers=headers, json={}).status_code == 409
    assert client.get(URL + "/bounded-one/autonomy", headers=headers).json["data"]["qualified"] is False
    assert app.config["NATIVE_ADAPTERS"]["dhan"].writes == []
