"""Bounded, operator-authored Practice entry rationale is optional and validated."""

import pytest
from flask import Flask

from flinttrade_core import practice_agent_runtime as runtime

pytestmark = pytest.mark.unit


def test_practice_config_defaults_to_no_entry_rationale():
    assert runtime.validate_practice_config({"symbols": ["RELIANCE"]})["entry_rationale"] == ""


@pytest.mark.parametrize(
    "rationale,expected",
    [
        ("", ""),
        ("  \n\t  ", ""),
        (
            "  Opening-range plan\n  with an operator-defined stop. \n",
            "Opening-range plan\n  with an operator-defined stop.",
        ),
        ("x" * 2000, "x" * 2000),
        ("  " + "x" * 2000 + "  ", "x" * 2000),
    ],
    ids=["empty", "whitespace", "multiline", "maximum", "trimmed-maximum"],
)
def test_practice_config_trims_but_does_not_rewrite_entry_rationale(rationale, expected):
    config = runtime.validate_practice_config({"symbols": ["RELIANCE"], "entry_rationale": rationale})
    assert config["entry_rationale"] == expected


@pytest.mark.parametrize(
    "rationale",
    [None, False, 1, 1.5, [], {}, "x" * 2001],
    ids=["null", "bool", "int", "float", "list", "object", "oversize"],
)
def test_invalid_entry_rationale_returns_400_before_runtime_construction(monkeypatch, rationale):
    app = Flask(__name__)
    app.add_url_rule("/start", view_func=runtime.start_practice_agent, methods=["POST"])
    monkeypatch.setattr(runtime, "_authorise", lambda: ("synthetic-token", "operator", None))
    monkeypatch.setattr(runtime, "_enabled", lambda: True)

    def unexpected_runtime(_app):
        pytest.fail("Invalid rationale must not construct a Practice supervisor")

    monkeypatch.setattr(runtime, "get_practice_supervisor", unexpected_runtime)
    result = app.test_client().post("/start", json={"symbols": ["RELIANCE"], "entry_rationale": rationale})
    assert result.status_code == 400
    assert "entry_rationale" in result.get_json()["message"]
