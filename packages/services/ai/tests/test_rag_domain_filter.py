"""Tests for DomainFilter — RAG pipeline topic guard.

Covers:
- TRADING_KEYWORDS frozenset has >= 50 entries.
- is_on_topic returns True for queries containing known trading keywords.
- is_on_topic returns False for clearly off-topic queries.
- is_on_topic is case-insensitive.
- REFUSAL_MESSAGE is the expected string.
- Extra keywords extend the set without replacing it.
- Semantic fallback is skipped when no embedding provider is set.
- RAGPipeline.query returns REFUSAL_MESSAGE for off-topic queries.
- RAGPipeline.query proceeds normally for on-topic queries.
- enable_domain_filter=False bypasses the filter entirely.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from flinttrade_ai.rag_pipeline import DomainFilter, RAGPipeline


# ---------------------------------------------------------------------------
# DomainFilter unit tests
# ---------------------------------------------------------------------------


class TestDomainFilterKeywords:
    """Tests for the TRADING_KEYWORDS frozenset."""

    def test_at_least_50_keywords(self) -> None:
        assert len(DomainFilter.TRADING_KEYWORDS) >= 50

    def test_keywords_are_lowercase(self) -> None:
        for kw in DomainFilter.TRADING_KEYWORDS:
            assert kw == kw.lower(), f"Keyword not lowercase: {kw!r}"

    def test_known_keywords_present(self) -> None:
        for kw in ("nifty", "option", "rsi", "delta", "straddle", "atr", "portfolio"):
            assert kw in DomainFilter.TRADING_KEYWORDS


class TestDomainFilterIsOnTopic:
    """Tests for DomainFilter.is_on_topic()."""

    def _filter(self) -> DomainFilter:
        return DomainFilter()  # No embedding provider → keyword-only

    # --- On-topic cases ---

    def test_nifty_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("What is the NIFTY trend today?")

    def test_options_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("Explain iron condor options strategy.")

    def test_stoploss_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("How should I set my stoploss?")

    def test_portfolio_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("Calculate portfolio risk exposure.")

    def test_rsi_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("RSI is at 70 — overbought signal?")

    def test_vix_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("India VIX is rising, what does that mean?")

    def test_case_insensitive_upper(self) -> None:
        assert self._filter().is_on_topic("BANKNIFTY CALL OPTIONS EXPIRY ANALYSIS")

    def test_case_insensitive_mixed(self) -> None:
        assert self._filter().is_on_topic("Delta-Neutral Hedging for Nifty Straddle")

    def test_backtest_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("How do I backtest a momentum strategy?")

    def test_margin_is_on_topic(self) -> None:
        assert self._filter().is_on_topic("What margin is required for 1 lot NIFTY fut?")

    # --- Off-topic cases ---

    def test_weather_is_off_topic(self) -> None:
        assert not self._filter().is_on_topic("What is the weather in Mumbai today?")

    def test_recipe_is_off_topic(self) -> None:
        assert not self._filter().is_on_topic("Give me a recipe for chocolate cake.")

    def test_sports_is_off_topic(self) -> None:
        assert not self._filter().is_on_topic("Who won the cricket match yesterday?")

    def test_generic_question_is_off_topic(self) -> None:
        assert not self._filter().is_on_topic("Tell me a joke.")

    def test_empty_query_is_off_topic(self) -> None:
        assert not self._filter().is_on_topic("")

    def test_whitespace_only_is_off_topic(self) -> None:
        assert not self._filter().is_on_topic("   ")


class TestDomainFilterExtraKeywords:
    """Tests for extra_keywords injection."""

    def test_extra_keyword_extends_match(self) -> None:
        f = DomainFilter(extra_keywords={"cryptobot"})
        assert f.is_on_topic("Deploy my cryptobot strategy")

    def test_extra_keywords_do_not_remove_defaults(self) -> None:
        f = DomainFilter(extra_keywords={"myterm"})
        assert f.is_on_topic("NIFTY analysis")

    def test_extra_keywords_lowercased_on_init(self) -> None:
        f = DomainFilter(extra_keywords={"MYCUSTOM"})
        assert f.is_on_topic("Use mycustom indicator")


class TestDomainFilterRefusalMessage:
    """Tests for the REFUSAL_MESSAGE constant."""

    def test_refusal_message_content(self) -> None:
        assert DomainFilter.REFUSAL_MESSAGE == (
            "I can only help with trading and market-related questions."
        )


class TestDomainFilterSemanticFallback:
    """Tests that semantic fallback is called when embedding provider is present."""

    def test_semantic_check_called_on_keyword_miss(self) -> None:
        """When no keyword matches, the embedding provider is consulted."""
        mock_provider = MagicMock()
        # Seed embedding — returns a high-similarity vector for "off-topic" text
        # Seed phrases produce cosine ~ 1.0 with the query
        mock_provider.embed.return_value = [[1.0, 0.0, 0.0]]

        f = DomainFilter(embedding_provider=mock_provider, semantic_threshold=0.9)
        # Query has no trading keywords but embedding returns high similarity
        f.is_on_topic("This has no finance keywords at all — just a sentence.")

        # embed called at least once (for seed and/or query)
        assert mock_provider.embed.called

    def test_embedding_failure_does_not_raise(self) -> None:
        """If semantic embeddings are unavailable, retrieval remains available."""
        mock_provider = MagicMock()
        mock_provider.embed.side_effect = RuntimeError("embed failed")

        f = DomainFilter(embedding_provider=mock_provider)
        result = f.is_on_topic("completely unrelated text about cooking")

        assert result is True

    def test_no_embedding_provider_skips_semantic(self) -> None:
        """Without an embedding provider, only keyword check is used."""
        f = DomainFilter(embedding_provider=None)
        # Off-topic — no keyword match, no semantic check
        assert not f.is_on_topic("How do I bake bread?")

    def test_adjusting_a_strategy_leg_is_recognised_without_semantic_similarity(self) -> None:
        provider = MagicMock()
        f = DomainFilter(embedding_provider=provider)

        assert f.is_on_topic("How do I adjust the second leg?")
        provider.embed.assert_not_called()


# ---------------------------------------------------------------------------
# RAGPipeline integration tests
# ---------------------------------------------------------------------------


def _make_mock_llm_response(content: str = "Answer here.") -> MagicMock:
    from flinttrade_ai.llm_client import LLMResponse

    mock = MagicMock()
    mock.chat.return_value = LLMResponse(content=content)
    return mock


class TestRAGPipelineDomainFilter:
    """Tests that RAGPipeline.query() uses DomainFilter as a pre-check."""

    def _make_pipeline(self, enable_filter: bool = True) -> RAGPipeline:
        """Build a RAGPipeline with a mocked LLM and manual domain filter."""
        mock_store = MagicMock()
        mock_store.search.return_value = [
            MagicMock(content="NIFTY is in a bullish trend.", source="doc.md",
                      doc_type="general", score=0.9, metadata={})
        ]
        mock_store.count.return_value = 1

        pipeline = RAGPipeline(
            llm_client=_make_mock_llm_response("Bullish NIFTY."),
            vector_store=mock_store,
            # Use a keyword-only filter (no real embeddings needed)
            domain_filter=DomainFilter(embedding_provider=None),
            enable_domain_filter=enable_filter,
        )
        return pipeline

    def test_on_topic_query_proceeds_to_retrieval(self) -> None:
        """An on-topic query reaches the vector store."""
        pipeline = self._make_pipeline()
        result = pipeline.query("What is the NIFTY trend?")

        # Should get an answer (not the refusal message)
        assert result.answer != DomainFilter.REFUSAL_MESSAGE

    def test_off_topic_query_returns_refusal(self) -> None:
        """An off-topic query returns the refusal message without retrieval."""
        pipeline = self._make_pipeline()
        result = pipeline.query("What is the best pizza recipe?")

        assert result.answer == DomainFilter.REFUSAL_MESSAGE
        assert result.error == ""

    def test_off_topic_query_skips_vector_store(self) -> None:
        """Off-topic query does not call the vector store."""
        mock_store = MagicMock()
        mock_store.count.return_value = 0

        pipeline = RAGPipeline(
            llm_client=_make_mock_llm_response(),
            vector_store=mock_store,
            domain_filter=DomainFilter(embedding_provider=None),
            enable_domain_filter=True,
        )
        pipeline.query("Tell me a bedtime story.")

        mock_store.search.assert_not_called()

    def test_filter_disabled_allows_off_topic(self) -> None:
        """With enable_domain_filter=False, off-topic queries proceed normally."""
        pipeline = self._make_pipeline(enable_filter=False)
        result = pipeline.query("Tell me a bedtime story.")

        # No refusal message — filter was bypassed
        assert result.answer != DomainFilter.REFUSAL_MESSAGE

    def test_no_llm_still_returns_error_not_refusal(self) -> None:
        """Without an LLM client, error message is about LLM, not domain."""
        mock_store = MagicMock()
        mock_store.count.return_value = 0

        pipeline = RAGPipeline(
            llm_client=None,
            vector_store=mock_store,
            domain_filter=DomainFilter(embedding_provider=None),
            enable_domain_filter=True,
        )
        result = pipeline.query("NIFTY trend analysis please")

        assert "No LLM" in result.error

    def test_result_has_query_field_set(self) -> None:
        """RAGResult.query is always set to the original question."""
        pipeline = self._make_pipeline()
        q = "What is RSI at 70 telling us?"
        result = pipeline.query(q)

        assert result.query == q
