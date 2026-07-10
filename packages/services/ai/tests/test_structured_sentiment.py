"""Tests for sentiment.py — all LLM calls are mocked.

No network access, no real LLM responses required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_client(content: str, success: bool = True) -> MagicMock:
    """Return a mock LLMClient whose .chat() returns a canned response."""
    mock_response = MagicMock()
    mock_response.success = success
    mock_response.content = content
    mock_response.error = "" if success else "LLM error"

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_response
    return mock_client


def _valid_payload() -> dict:
    """Return a valid MARKET_SUMMARY_SCHEMA-conformant dict."""
    return {
        "sentiment_score": 4.5,
        "market_sentiment": "BULLISH",
        "indices": [
            {"name": "NIFTY 50", "value": 24350.0, "change_pct": 0.45, "signal": "BUY"},
            {"name": "BANK NIFTY", "value": 51200.0, "change_pct": -0.12, "signal": "HOLD"},
        ],
        "sectors": [
            {"name": "IT", "performance": "Outperforming", "outlook": "Strong earnings season expected."},
            {"name": "FMCG", "performance": "Neutral", "outlook": "Monsoon demand awaited."},
        ],
        "key_points": [
            "FIIs turned net buyers after three days of selling.",
            "IT index hits 52-week high on positive guidance.",
            "Bank Nifty consolidates near support.",
        ],
        "fii_dii_flow": {
            "fii_net": 1250.0,
            "dii_net": -430.0,
            "interpretation": "Foreign buying offset by domestic profit-booking.",
        },
        "risks": ["Crude above $90", "US Fed hawkish signal"],
        "opportunities": ["IT sector breakout", "Mid-cap momentum"],
    }


def _market_data(**extra: object) -> dict:
    """Return complete provider data for trusted live numeric fields."""
    data: dict[str, object] = {
        "indices": [
            {"name": "NIFTY 50", "value": 24350.0, "change_pct": 0.45},
            {"name": "BANK NIFTY", "value": 51200.0, "change_pct": -0.12},
        ],
        "fii_dii_flow": {"fii_net": 1250.0, "dii_net": -430.0},
    }
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# SentimentLabel
# ---------------------------------------------------------------------------


class TestSentimentLabel:
    def test_all_labels_defined(self):
        from flinttrade_ai.sentiment import SentimentLabel

        labels = {label.value for label in SentimentLabel}
        assert "STRONGLY_BULLISH" in labels
        assert "STRONGLY_BEARISH" in labels
        assert "NEUTRAL" in labels

    def test_str_values(self):
        from flinttrade_ai.sentiment import SentimentLabel

        # StrEnum — str(label) == label.value
        assert str(SentimentLabel.BULLISH) == "BULLISH"


# ---------------------------------------------------------------------------
# MARKET_SUMMARY_SCHEMA structure
# ---------------------------------------------------------------------------


class TestMarketSummarySchema:
    def test_schema_has_required_fields(self):
        from flinttrade_ai.sentiment import MARKET_SUMMARY_SCHEMA

        schema = MARKET_SUMMARY_SCHEMA["json_schema"]["schema"]
        required = schema["required"]
        for field in [
            "sentiment_score",
            "market_sentiment",
            "indices",
            "sectors",
            "key_points",
            "fii_dii_flow",
            "risks",
            "opportunities",
        ]:
            assert field in required, f"'{field}' missing from schema required list"

    def test_sentiment_score_bounds(self):
        from flinttrade_ai.sentiment import MARKET_SUMMARY_SCHEMA

        props = MARKET_SUMMARY_SCHEMA["json_schema"]["schema"]["properties"]
        score_prop = props["sentiment_score"]
        assert score_prop["minimum"] == -10
        assert score_prop["maximum"] == 10

    def test_market_sentiment_enum_values(self):
        from flinttrade_ai.sentiment import MARKET_SUMMARY_SCHEMA, SentimentLabel

        props = MARKET_SUMMARY_SCHEMA["json_schema"]["schema"]["properties"]
        enum_values = props["market_sentiment"]["enum"]
        for label in SentimentLabel:
            assert label.value in enum_values

    def test_indices_items_have_signal(self):
        from flinttrade_ai.sentiment import MARKET_SUMMARY_SCHEMA

        props = MARKET_SUMMARY_SCHEMA["json_schema"]["schema"]["properties"]
        idx_items = props["indices"]["items"]
        assert "signal" in idx_items["properties"]
        assert "BUY" in idx_items["properties"]["signal"]["enum"]

    def test_fii_dii_flow_subfields(self):
        from flinttrade_ai.sentiment import MARKET_SUMMARY_SCHEMA

        props = MARKET_SUMMARY_SCHEMA["json_schema"]["schema"]["properties"]
        flow_props = props["fii_dii_flow"]["properties"]
        assert "fii_net" in flow_props
        assert "dii_net" in flow_props
        assert "interpretation" in flow_props


# ---------------------------------------------------------------------------
# MarketSummary Pydantic model
# ---------------------------------------------------------------------------


class TestMarketSummaryModel:
    def test_valid_payload_parses(self):
        from flinttrade_ai.sentiment import MarketSummary

        m = MarketSummary.model_validate(_valid_payload())
        assert m.sentiment_score == pytest.approx(4.5)
        assert m.market_sentiment.value == "BULLISH"
        assert len(m.indices) == 2
        assert len(m.sectors) == 2
        assert len(m.key_points) == 3

    def test_score_clamped_to_bounds(self):
        from flinttrade_ai.sentiment import MarketSummary

        data = _valid_payload()
        data["sentiment_score"] = 15.0  # Out of range
        m = MarketSummary.model_validate(data)
        assert m.sentiment_score == pytest.approx(10.0)

        data["sentiment_score"] = -99.0
        m = MarketSummary.model_validate(data)
        assert m.sentiment_score == pytest.approx(-10.0)

    def test_label_normalised_to_uppercase(self):
        from flinttrade_ai.sentiment import MarketSummary, SentimentLabel

        data = _valid_payload()
        data["market_sentiment"] = "bullish"  # lowercase from LLM
        m = MarketSummary.model_validate(data)
        assert m.market_sentiment == SentimentLabel.BULLISH

    def test_fii_dii_flow_parses(self):
        from flinttrade_ai.sentiment import MarketSummary

        m = MarketSummary.model_validate(_valid_payload())
        assert m.fii_dii_flow.fii_net == pytest.approx(1250.0)
        assert m.fii_dii_flow.dii_net == pytest.approx(-430.0)
        assert "Foreign" in m.fii_dii_flow.interpretation

    def test_risks_and_opportunities(self):
        from flinttrade_ai.sentiment import MarketSummary

        m = MarketSummary.model_validate(_valid_payload())
        assert len(m.risks) == 2
        assert len(m.opportunities) == 2

    def test_label_from_score_method(self):
        from flinttrade_ai.sentiment import MarketSummary, SentimentLabel

        data = _valid_payload()
        data["sentiment_score"] = 8.0
        data["market_sentiment"] = "STRONGLY_BULLISH"
        m = MarketSummary.model_validate(data)
        assert m.label_from_score() == SentimentLabel.STRONGLY_BULLISH

    def test_label_is_always_derived_from_score(self):
        from flinttrade_ai.sentiment import MarketSummary, SentimentLabel

        data = _valid_payload()
        data["sentiment_score"] = 8.0
        data["market_sentiment"] = "BEARISH"

        m = MarketSummary.model_validate(data)

        assert m.market_sentiment == SentimentLabel.STRONGLY_BULLISH

    def test_to_display_dict_is_serialisable(self):
        from flinttrade_ai.sentiment import MarketSummary

        m = MarketSummary.model_validate(_valid_payload())
        d = m.to_display_dict()
        # Must round-trip through JSON without errors
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["sentiment_score"] == pytest.approx(4.5)

    def test_key_points_min_items_validation(self):
        from flinttrade_ai.sentiment import MarketSummary

        data = _valid_payload()
        data["key_points"] = ["Only one point."]  # Too few
        with pytest.raises(Exception):
            MarketSummary.model_validate(data)

    def test_key_points_max_items_validation(self):
        from flinttrade_ai.sentiment import MarketSummary

        data = _valid_payload()
        data["key_points"] = [f"Point {i}" for i in range(6)]  # Too many
        with pytest.raises(Exception):
            MarketSummary.model_validate(data)


# ---------------------------------------------------------------------------
# sentiment_label_from_score standalone utility
# ---------------------------------------------------------------------------


class TestSentimentLabelFromScore:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (10.0, "STRONGLY_BULLISH"),
            (7.0, "STRONGLY_BULLISH"),
            (6.9, "BULLISH"),
            (3.0, "BULLISH"),
            (2.9, "NEUTRAL"),
            (0.0, "NEUTRAL"),
            (-2.9, "NEUTRAL"),
            (-3.0, "BEARISH"),
            (-6.9, "BEARISH"),
            (-7.0, "STRONGLY_BEARISH"),
            (-10.0, "STRONGLY_BEARISH"),
        ],
    )
    def test_score_to_label_boundaries(self, score: float, expected: str):
        from flinttrade_ai.sentiment import sentiment_label_from_score

        result = sentiment_label_from_score(score)
        assert result.value == expected

    def test_out_of_range_clamped(self):
        from flinttrade_ai.sentiment import (
            SentimentLabel,
            sentiment_label_from_score,
        )

        assert sentiment_label_from_score(999) == SentimentLabel.STRONGLY_BULLISH
        assert sentiment_label_from_score(-999) == SentimentLabel.STRONGLY_BEARISH


# ---------------------------------------------------------------------------
# generate_market_summary
# ---------------------------------------------------------------------------


class TestGenerateMarketSummary:
    def test_returns_market_summary_on_valid_response(self):
        from flinttrade_ai.sentiment import MarketSummary, generate_market_summary

        client = _make_llm_client(json.dumps(_valid_payload()))
        result = generate_market_summary(client, _market_data())
        assert isinstance(result, MarketSummary)
        assert result.sentiment_score == pytest.approx(4.5)

    def test_returns_none_on_llm_failure(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client("", success=False)
        result = generate_market_summary(client, _market_data())
        assert result is None

    def test_returns_none_on_invalid_json(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client("This is not JSON at all.")
        result = generate_market_summary(client, _market_data())
        assert result is None

    def test_strips_markdown_fences(self):
        """LLM sometimes wraps JSON in ```json ... ``` fences."""
        from flinttrade_ai.sentiment import MarketSummary, generate_market_summary

        wrapped = "```json\n" + json.dumps(_valid_payload()) + "\n```"
        client = _make_llm_client(wrapped)
        result = generate_market_summary(client, _market_data())
        assert isinstance(result, MarketSummary)

    def test_returns_none_on_schema_mismatch(self):
        from flinttrade_ai.sentiment import generate_market_summary

        bad_payload = {"wrong_field": "value"}
        client = _make_llm_client(json.dumps(bad_payload))
        result = generate_market_summary(client, _market_data())
        assert result is None

    def test_chat_called_with_messages(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client(json.dumps(_valid_payload()))
        generate_market_summary(client, _market_data())
        client.chat.assert_called_once()
        call_args = client.chat.call_args
        messages = call_args[0][0]  # Positional first arg
        # Should have system + user messages
        assert len(messages) == 2
        roles = [m.role for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_market_data_embedded_in_prompt(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client(json.dumps(_valid_payload()))
        generate_market_summary(client, _market_data(fii_net_crore=-1500))
        messages = client.chat.call_args[0][0]
        user_msg = next(m for m in messages if m.role == "user")
        assert "fii_net_crore" in user_msg.content

    def test_llm_exception_returns_none(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = MagicMock()
        client.chat.side_effect = RuntimeError("connection refused")
        result = generate_market_summary(client, _market_data())
        assert result is None

    def test_does_not_force_response_format(self):
        # Reasoning models on LM Studio return empty content when a json_schema
        # grammar is applied (verified live against qwen3.6), so generate_market_summary
        # must rely on prompt-only JSON rather than forcing response_format.
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client(json.dumps(_valid_payload()))
        generate_market_summary(client, _market_data())
        kwargs = client.chat.call_args.kwargs
        assert "response_format" not in kwargs

    def test_prompt_lists_every_required_schema_field(self):
        # Without response_format the prompt is the only thing telling the model
        # which keys to emit. If it omits the field names, reasoning models invent
        # their own structure (verified live: 'flows', 'analyst_summary', etc.)
        # and validation fails. The prompt must name every required field AND enum
        # value the schema defines, including NESTED ones (indices.signal,
        # fii_dii_flow.fii_net, …) — those are exactly the keys a human is most
        # likely to forget when editing the hand-written skeleton.
        from flinttrade_ai.sentiment import (
            MARKET_SUMMARY_SCHEMA,
            generate_market_summary,
        )

        def walk(node: object) -> list[str]:
            """Collect every `required` key name and `enum` value, recursively."""
            tokens: list[str] = []
            if isinstance(node, dict):
                tokens += node.get("required", [])
                tokens += node.get("enum", [])
                for value in node.values():
                    tokens += walk(value)
            elif isinstance(node, list):
                for value in node:
                    tokens += walk(value)
            return tokens

        client = _make_llm_client(json.dumps(_valid_payload()))
        generate_market_summary(client, _market_data())
        prompt_text = " ".join(m.content for m in client.chat.call_args[0][0])
        for token in walk(MARKET_SUMMARY_SCHEMA["json_schema"]["schema"]):
            assert token in prompt_text, f"prompt missing schema token: {token}"

    def test_temperature_passed_to_client(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client(json.dumps(_valid_payload()))
        generate_market_summary(client, _market_data(), temperature=0.1)
        kwargs = client.chat.call_args[1]
        assert kwargs.get("temperature") == pytest.approx(0.1)

    def test_strongly_bearish_label(self):
        from flinttrade_ai.sentiment import MarketSummary, generate_market_summary

        payload = _valid_payload()
        payload["sentiment_score"] = -8.0
        payload["market_sentiment"] = "STRONGLY_BEARISH"
        client = _make_llm_client(json.dumps(payload))
        result = generate_market_summary(client, _market_data())
        assert isinstance(result, MarketSummary)
        assert result.market_sentiment.value == "STRONGLY_BEARISH"

    def test_incomplete_provider_data_is_rejected_before_llm_call(self):
        from flinttrade_ai.sentiment import generate_market_summary

        client = _make_llm_client(json.dumps(_valid_payload()))

        result = generate_market_summary(client, {"nifty": 24350})

        assert result is None
        client.chat.assert_not_called()

    def test_provider_numerics_replace_llm_generated_values(self):
        from flinttrade_ai.sentiment import generate_market_summary

        payload = _valid_payload()
        payload["indices"] = [
            {"name": "NIFTY 50", "value": 99999.0, "change_pct": 9.9, "signal": "BUY"},
            {"name": "FABRICATED INDEX", "value": 1.0, "change_pct": 8.0, "signal": "BUY"},
        ]
        payload["fii_dii_flow"] = {
            "fii_net": 99999.0,
            "dii_net": -99999.0,
            "interpretation": "Narrative remains model-authored.",
        }
        client = _make_llm_client(json.dumps(payload))

        result = generate_market_summary(client, _market_data())

        assert result is not None
        assert [(item.name, item.value, item.change_pct) for item in result.indices] == [
            ("NIFTY 50", 24350.0, 0.45),
            ("BANK NIFTY", 51200.0, -0.12),
        ]
        assert result.indices[0].signal.value == "BUY"
        assert result.indices[1].signal.value == "HOLD"
        assert result.fii_dii_flow.fii_net == pytest.approx(1250.0)
        assert result.fii_dii_flow.dii_net == pytest.approx(-430.0)
        assert result.fii_dii_flow.interpretation == "Narrative remains model-authored."


# ---------------------------------------------------------------------------
# IndexSnapshot and SectorOutlook sub-models
# ---------------------------------------------------------------------------


class TestSubModels:
    def test_index_snapshot_fields(self):
        from flinttrade_ai.sentiment import IndexSignal, IndexSnapshot

        snap = IndexSnapshot(name="NIFTY 50", value=24350.0, change_pct=0.45, signal=IndexSignal.BUY)
        assert snap.name == "NIFTY 50"
        assert snap.signal == IndexSignal.BUY

    def test_sector_outlook_fields(self):
        from flinttrade_ai.sentiment import SectorOutlook

        sector = SectorOutlook(name="IT", performance="Outperforming", outlook="Strong earnings ahead.")
        assert sector.name == "IT"

    def test_fii_dii_flow_fields(self):
        from flinttrade_ai.sentiment import FiiDiiFlow

        flow = FiiDiiFlow(fii_net=1200.0, dii_net=-300.0, interpretation="Net positive.")
        assert flow.fii_net == pytest.approx(1200.0)
        assert flow.dii_net == pytest.approx(-300.0)


def test_package_root_exports_canonical_structured_sentiment() -> None:
    from flinttrade_ai import (
        FiiDiiFlow,
        IndexSignal,
        IndexSnapshot,
        MarketSummary,
        SectorOutlook,
        SentimentLabel,
        generate_market_summary,
        sentiment_label_from_score,
    )
    from flinttrade_ai import sentiment

    assert FiiDiiFlow is sentiment.FiiDiiFlow
    assert IndexSignal is sentiment.IndexSignal
    assert IndexSnapshot is sentiment.IndexSnapshot
    assert MarketSummary is sentiment.MarketSummary
    assert SectorOutlook is sentiment.SectorOutlook
    assert SentimentLabel is sentiment.SentimentLabel
    assert generate_market_summary is sentiment.generate_market_summary
    assert sentiment_label_from_score is sentiment.sentiment_label_from_score
