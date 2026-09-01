"""Tests for TradedMemory — 4-layer persistent trading memory system.

Each test gets a unique collection_prefix (via uuid4) so in-memory state
does not bleed between tests. Persistence tests reopen a second instance
against the same directory and must not import chromadb.
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone
from typing import get_type_hints
from unittest.mock import MagicMock

import numpy as np
import pytest

from flinttrade_ai.memory import (
    CATEGORY_IMPORTANCE,
    HierarchicalMemoryManager,
    MemoryBackend,
    MemoryBackendConfig,
    MemoryBackendKind,
    MemoryEntry,
    MemoryItem,
    MemoryLayer,
    MemoryQueryResult,
    TradedMemory,
    compound_score,
    create_memory_backend,
    exponential_decay,
    initial_importance,
)


class _DeterministicEmbeddingFunction:
    """Fast ChromaDB-compatible embedder for unit tests."""

    @staticmethod
    def name() -> str:
        return "flinttrade-test-deterministic"

    @staticmethod
    def default_space() -> str:
        return "l2"

    @staticmethod
    def supported_spaces() -> list[str]:
        return ["l2", "cosine"]

    @staticmethod
    def get_config() -> dict[str, str]:
        return {}

    @staticmethod
    def validate_config(config: dict[str, str]) -> None:
        return None

    @classmethod
    def build_from_config(cls, config: dict[str, str]) -> "_DeterministicEmbeddingFunction":
        return cls()

    @staticmethod
    def is_legacy() -> bool:
        return False

    def __call__(self, input):
        documents = [input] if isinstance(input, str) else list(input)
        return [self._embed(str(document)) for document in documents]

    def embed_query(self, input):
        return self.__call__(input)

    @staticmethod
    def _embed(text: str) -> np.ndarray:
        lowered = text.lower()
        return np.array(
            [
                float("nifty" in lowered),
                float("reliance" in lowered),
                float("tcs" in lowered),
                float("bullish" in lowered or "trend" in lowered or "signal" in lowered),
                float("persistent" in lowered or "specific" in lowered or "memory" in lowered),
                min(len(text) / 100.0, 1.0),
            ],
            dtype=np.float32,
        )


_TEST_EMBEDDING_FN = _DeterministicEmbeddingFunction()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_memory(**kwargs) -> TradedMemory:
    """Create a TradedMemory with a unique collection prefix for test isolation."""
    prefix = f"test_{uuid.uuid4().hex[:8]}"
    defaults = dict(
        persist_dir="",
        collection_prefix=prefix,
        _embedding_fn=_TEST_EMBEDDING_FN,
    )
    defaults.update(kwargs)
    return TradedMemory(**defaults)


@pytest.fixture
def memory() -> TradedMemory:
    """Fresh isolated TradedMemory instance for each test."""
    return make_memory()


def test_close_releases_owned_vector_client_once() -> None:
    client = MagicMock()
    memory = TradedMemory(persist_dir="", _chroma_client=client)

    memory.close()
    memory.close()

    client.close.assert_called_once_with()
    with pytest.raises(RuntimeError, match="learning memory is closed"):
        memory._get_client()


# ---------------------------------------------------------------------------
# Scoring function tests
# ---------------------------------------------------------------------------


class TestExponentialDecay:
    """Tests for the exponential_decay scoring function."""

    def test_exponential_decay_at_zero(self) -> None:
        # Arrange / Act
        result = exponential_decay(0, k=10.0)
        # Assert: at day 0, weight should be exactly 1.0
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_exponential_decay_at_k_days(self) -> None:
        # Arrange
        k = 10.0
        # Act
        result = exponential_decay(int(k), k=k)
        # Assert: after k days, ~37% (1/e) weight should remain
        assert result == pytest.approx(1.0 / math.e, rel=1e-6)

    def test_exponential_decay_strictly_decreasing(self) -> None:
        # Arrange / Act
        scores = [exponential_decay(d, k=10.0) for d in range(0, 50, 5)]
        # Assert
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1]

    def test_exponential_decay_never_negative(self) -> None:
        for delta in [0, 5, 30, 100, 365]:
            assert exponential_decay(delta) >= 0.0


class TestCompoundScore:
    """Tests for the compound_score ranking function."""

    def test_compound_score_higher_importance_wins(self) -> None:
        # Arrange — same similarity and recency, different importance
        score_high = compound_score(similarity=0.8, recency_delta=5, importance=80.0)
        score_low = compound_score(similarity=0.8, recency_delta=5, importance=50.0)
        # Assert
        assert score_high > score_low

    def test_compound_score_fresher_memory_wins(self) -> None:
        # Arrange — same similarity and importance, different recency
        score_fresh = compound_score(similarity=0.7, recency_delta=0, importance=60.0)
        score_old = compound_score(similarity=0.7, recency_delta=30, importance=60.0)
        # Assert
        assert score_fresh > score_old

    def test_compound_score_higher_similarity_wins(self) -> None:
        # Arrange — same recency and importance
        score_high = compound_score(similarity=0.95, recency_delta=5, importance=65.0)
        score_low = compound_score(similarity=0.5, recency_delta=5, importance=65.0)
        # Assert
        assert score_high > score_low

    def test_compound_score_is_non_negative(self) -> None:
        # All components should produce non-negative output
        result = compound_score(similarity=0.0, recency_delta=365, importance=0.0)
        assert result >= 0.0

    def test_compound_score_defaults_to_legacy_percent_scale_at_one(self) -> None:
        result = compound_score(similarity=0.0, recency_delta=0, importance=1.0)
        assert result == pytest.approx(0.02)


class TestUnifiedMemoryEntry:
    """The persistent and in-process backends share one canonical model."""

    def test_memory_item_is_a_compatibility_alias(self) -> None:
        assert MemoryItem is MemoryEntry

    def test_legacy_persistent_shape_normalises_percent_importance(self) -> None:
        entry = MemoryItem(
            id="legacy-id",
            symbol="NIFTY",
            text="Legacy memory",
            layer=MemoryLayer.SHORT,
            importance=65.0,
            recency_delta=3,
            access_count=1,
            timestamp=datetime.now(timezone.utc),
        )

        assert entry.content == "Legacy memory"
        assert entry.text == "Legacy memory"
        assert entry.importance == pytest.approx(0.65)
        assert entry.importance_percent == pytest.approx(65.0)

    def test_legacy_persistent_shape_treats_one_as_one_percent(self) -> None:
        entry = MemoryItem(
            id="legacy-one",
            symbol="NIFTY",
            text="One percent memory",
            layer=MemoryLayer.SHORT,
            importance=1.0,
            recency_delta=0,
            access_count=0,
            timestamp=datetime.now(timezone.utc),
        )

        assert entry.importance == pytest.approx(0.01)

    def test_legacy_positional_constructor_remains_available(self) -> None:
        timestamp = datetime.now(timezone.utc)
        entry = MemoryItem(
            "legacy-positional",
            "NIFTY",
            "Positional memory",
            MemoryLayer.SHORT,
            1.0,
            2,
            3,
            timestamp,
            {"source": "legacy"},
        )

        assert entry.id == "legacy-positional"
        assert entry.text == "Positional memory"
        assert entry.importance == pytest.approx(0.01)
        assert entry.metadata == {"source": "legacy"}

    def test_symbol_does_not_change_importance_units(self) -> None:
        with pytest.raises(Exception):
            MemoryEntry(
                content="Ambiguous importance",
                symbol="NIFTY",
                category="signal",
                importance=5.0,
            )

    def test_legacy_last_accessed_metadata_remains_caller_data(self, memory: TradedMemory) -> None:
        entry = memory._item_from_meta(
            "legacy-metadata",
            "Legacy metadata memory",
            {
                "symbol": "NIFTY",
                "layer": MemoryLayer.SHORT.value,
                "importance": 50.0,
                "recency_delta": 0,
                "access_count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "last_accessed": "manual-caller-metadata",
            },
        )

        assert entry.last_accessed is None
        assert entry.metadata["last_accessed"] == "manual-caller-metadata"

    def test_legacy_category_metadata_remains_caller_data(self, memory: TradedMemory) -> None:
        entry = memory._item_from_meta(
            "legacy-category",
            "Legacy category memory",
            {
                "symbol": "NIFTY",
                "layer": MemoryLayer.SHORT.value,
                "importance": 50.0,
                "recency_delta": 0,
                "access_count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "category": "manual-caller-category",
            },
        )

        assert entry.category == "analysis"
        assert entry.metadata["category"] == "manual-caller-category"


class TestInitialImportance:
    """Tests for layer-differentiated initial importance sampling."""

    def test_initial_importance_layer_ranges(self) -> None:
        # Arrange
        expected_ranges = {
            MemoryLayer.SHORT: (50.0, 70.0),
            MemoryLayer.MID: (55.0, 75.0),
            MemoryLayer.LONG: (60.0, 80.0),
            MemoryLayer.REFLECTION: (70.0, 90.0),
        }
        # Act / Assert — run many samples to verify bounds
        for layer, (lo, hi) in expected_ranges.items():
            for _ in range(20):
                value = initial_importance(layer)
                assert lo <= value <= hi, f"{layer.value} importance {value:.2f} outside [{lo}, {hi}]"

    def test_add_memory_layer_importance_range(self, memory: TradedMemory) -> None:
        # Arrange — add memories across layers and verify stored importance
        layer_ranges = {
            MemoryLayer.SHORT: (50.0, 70.0),
            MemoryLayer.LONG: (60.0, 80.0),
        }
        for layer, (lo, hi) in layer_ranges.items():
            mem_id = memory.add_memory("NIFTY", "test importance range", layer)
            # Retrieve the raw metadata to verify importance was stored in range
            collection = memory._get_collection(layer)
            result = collection.get(ids=[mem_id])
            importance = float(result["metadatas"][0]["importance"])
            assert lo <= importance <= hi, f"{layer.value}: importance {importance:.2f} outside [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# TradedMemory core behaviour
# ---------------------------------------------------------------------------


class TestAddMemory:
    """Tests for TradedMemory.add_memory."""

    def test_add_memory_returns_id(self, memory: TradedMemory) -> None:
        # Act
        mem_id = memory.add_memory("NIFTY", "Bullish trend forming", MemoryLayer.SHORT)
        # Assert
        assert isinstance(mem_id, str)
        assert len(mem_id) > 0

    def test_add_memory_returns_unique_ids(self, memory: TradedMemory) -> None:
        # Act
        ids = [memory.add_memory("NIFTY", f"memory {i}", MemoryLayer.SHORT) for i in range(5)]
        # Assert — all IDs must be unique
        assert len(set(ids)) == 5

    def test_add_memory_stores_metadata(self, memory: TradedMemory) -> None:
        # Arrange
        extra_meta = {"source": "news", "confidence": "high"}
        # Act
        mem_id = memory.add_memory("RELIANCE", "Q2 earnings beat", MemoryLayer.MID, metadata=extra_meta)
        collection = memory._get_collection(MemoryLayer.MID)
        result = collection.get(ids=[mem_id])
        # Assert
        stored_meta = result["metadatas"][0]
        assert stored_meta["source"] == "news"
        assert stored_meta["confidence"] == "high"
        assert stored_meta["symbol"] == "RELIANCE"
        assert stored_meta["layer"] == MemoryLayer.MID.value

    def test_add_memory_initialises_recency_delta_at_zero(self, memory: TradedMemory) -> None:
        # Act
        mem_id = memory.add_memory("TCS", "Strong order book", MemoryLayer.LONG)
        collection = memory._get_collection(MemoryLayer.LONG)
        result = collection.get(ids=[mem_id])
        # Assert
        assert int(result["metadatas"][0]["recency_delta"]) == 0

    def test_category_can_seed_initial_importance(self, memory: TradedMemory) -> None:
        mem_id = memory.add_memory(
            "NIFTY",
            "Completed trade outcome",
            MemoryLayer.REFLECTION,
            category="trade",
        )
        collection = memory._get_collection(MemoryLayer.REFLECTION)
        stored = collection.get(ids=[mem_id])["metadatas"][0]

        assert stored["_flinttrade_category"] == "trade"
        assert float(stored["importance"]) == pytest.approx(CATEGORY_IMPORTANCE["trade"] * 100.0)

    def test_add_memory_importance_scale_is_explicit(self, memory: TradedMemory) -> None:
        normalised_id = memory.add_memory(
            "NIFTY",
            "normalised importance",
            MemoryLayer.SHORT,
            importance=1.01,
        )
        percent_id = memory.add_memory(
            "NIFTY",
            "percent importance",
            MemoryLayer.SHORT,
            importance=1.0,
            importance_scale="percent",
        )
        collection = memory._get_collection(MemoryLayer.SHORT)

        normalised = collection.get(ids=[normalised_id])["metadatas"][0]
        percent = collection.get(ids=[percent_id])["metadatas"][0]
        assert float(normalised["importance"]) == pytest.approx(100.0)
        assert float(percent["importance"]) == pytest.approx(1.0)

    def test_invalid_importance_scale_is_rejected(self, memory: TradedMemory) -> None:
        with pytest.raises(ValueError, match="importance_scale"):
            memory.add_memory(
                "NIFTY",
                "invalid scale",
                MemoryLayer.SHORT,
                importance=0.5,
                importance_scale="invalid",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError, match="importance_scale"):
            compound_score(
                similarity=0.5,
                recency_delta=0,
                importance=0.5,
                importance_scale="invalid",  # type: ignore[arg-type]
            )

    def test_common_add_and_retrieve_interface(self, memory: TradedMemory) -> None:
        mem_id = memory.add(
            "NIFTY breakout confirmed",
            category="signal",
            symbol="NIFTY",
            layer=MemoryLayer.SHORT,
        )

        entries = memory.retrieve(
            "breakout confirmed",
            top_k=1,
            symbol="NIFTY",
            layer=MemoryLayer.SHORT,
        )

        assert [entry.id for entry in entries] == [mem_id]
        assert entries[0].category == "signal"
        assert entries[0].importance == pytest.approx(CATEGORY_IMPORTANCE["signal"])

    def test_common_add_clamps_importance_like_in_process_backend(self, memory: TradedMemory) -> None:
        memory.add(
            "NIFTY high importance",
            category="signal",
            importance=5.0,
            symbol="NIFTY",
            layer=MemoryLayer.SHORT,
        )

        entry = memory.retrieve(
            "high importance",
            symbol="NIFTY",
            layer=MemoryLayer.SHORT,
            top_k=1,
        )[0]

        assert entry.importance == pytest.approx(1.0)

    def test_common_retrieve_keeps_cross_layer_query_ranking(
        self,
        memory: TradedMemory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        weak_match = MemoryEntry(
            content="weak match",
            symbol="NIFTY",
            layer=MemoryLayer.SHORT,
            category="signal",
            importance=1.0,
        )
        strong_match = MemoryEntry(
            content="strong match",
            symbol="NIFTY",
            layer=MemoryLayer.LONG,
            category="analysis",
            importance=0.1,
        )
        weak_match._retrieval_score = 0.2
        strong_match._retrieval_score = 0.9

        def fake_get_memories(
            symbol: str | None,
            query: str,
            layer: MemoryLayer,
            n: int = 3,
            *,
            _update_access: bool = True,
        ) -> MemoryQueryResult:
            del symbol, n, _update_access
            items = {
                MemoryLayer.SHORT: [weak_match],
                MemoryLayer.LONG: [strong_match],
            }.get(layer, [])
            return MemoryQueryResult(items=items, query=query, layer=layer)

        monkeypatch.setattr(memory, "get_memories", fake_get_memories)
        monkeypatch.setattr(memory, "_record_retrieval", lambda entry: None)

        entries = memory.retrieve("strong match", top_k=2, symbol="NIFTY")

        assert [entry.content for entry in entries] == ["strong match", "weak match"]

    def test_common_retrieve_reinforces_only_global_top_k(self, memory: TradedMemory) -> None:
        short_id = memory.add_memory(
            "NIFTY",
            "shared query short",
            MemoryLayer.SHORT,
            importance=1.0,
        )
        long_id = memory.add_memory(
            "NIFTY",
            "shared query long",
            MemoryLayer.LONG,
            importance=0.01,
        )

        entries = memory.retrieve("shared query", top_k=1, symbol="NIFTY")

        short_meta = memory._get_collection(MemoryLayer.SHORT).get(ids=[short_id])["metadatas"][0]
        long_meta = memory._get_collection(MemoryLayer.LONG).get(ids=[long_id])["metadatas"][0]
        assert entries[0].id == short_id
        assert int(short_meta["access_count"]) == 1
        assert int(long_meta["access_count"]) == 0

    def test_empty_symbol_is_an_exact_scope(self, memory: TradedMemory) -> None:
        unscoped_id = memory.add(
            "shared empty-symbol query",
            category="signal",
            symbol="",
            layer=MemoryLayer.SHORT,
        )
        memory.add(
            "NIFTY empty-symbol query",
            category="signal",
            symbol="NIFTY",
            layer=MemoryLayer.SHORT,
        )

        entries = memory.retrieve(
            "empty-symbol query",
            symbol="",
            layer=MemoryLayer.SHORT,
            top_k=5,
        )

        assert [entry.id for entry in entries] == [unscoped_id]


class TestGetMemories:
    """Tests for TradedMemory.get_memories."""

    def test_get_memories_returns_top_n(self, memory: TradedMemory) -> None:
        # Arrange — add several memories for the same symbol / layer
        for i in range(6):
            memory.add_memory("NIFTY", f"NIFTY bullish signal {i}", MemoryLayer.SHORT)
        # Act
        result = memory.get_memories("NIFTY", "bullish trend", MemoryLayer.SHORT, n=3)
        # Assert
        assert isinstance(result, MemoryQueryResult)
        assert len(result.items) <= 3

    def test_get_memories_empty_returns_empty(self, memory: TradedMemory) -> None:
        # Act — no memories stored
        result = memory.get_memories("BANKNIFTY", "some query", MemoryLayer.LONG, n=5)
        # Assert
        assert result.items == []
        assert result.query == "some query"
        assert result.layer == MemoryLayer.LONG

    def test_get_memories_filters_by_symbol(self, memory: TradedMemory) -> None:
        # Arrange — store for two different symbols in same layer
        memory.add_memory("NIFTY", "NIFTY specific memory", MemoryLayer.SHORT)
        memory.add_memory("RELIANCE", "RELIANCE specific memory", MemoryLayer.SHORT)
        # Act — query for only NIFTY
        result = memory.get_memories("NIFTY", "specific memory", MemoryLayer.SHORT, n=5)
        # Assert — only NIFTY memories returned
        for item in result.items:
            assert item.symbol == "NIFTY"

    def test_get_memories_reranks_by_compound_score(self, memory: TradedMemory) -> None:
        # Arrange — manually tweak importance to make one memory clearly dominant
        # Store two memories, then artificially raise one's importance via update
        id_low = memory.add_memory("NIFTY", "low importance memory about NIFTY trend", MemoryLayer.SHORT)
        id_high = memory.add_memory("NIFTY", "high importance memory about NIFTY trend", MemoryLayer.SHORT)

        # Directly set importance in ChromaDB
        collection = memory._get_collection(MemoryLayer.SHORT)
        low_meta = collection.get(ids=[id_low])["metadatas"][0]
        high_meta = collection.get(ids=[id_high])["metadatas"][0]
        collection.update(ids=[id_low], metadatas=[{**low_meta, "importance": 50.0}])
        collection.update(ids=[id_high], metadatas=[{**high_meta, "importance": 90.0}])

        # Act
        result = memory.get_memories("NIFTY", "NIFTY trend memory", MemoryLayer.SHORT, n=2)

        # Assert — high-importance memory should rank first
        assert len(result.items) == 2
        assert result.items[0].id == id_high

    def test_get_memories_increments_access_count(self, memory: TradedMemory) -> None:
        # Arrange
        mem_id = memory.add_memory("NIFTY", "NIFTY access count test", MemoryLayer.SHORT)
        # Act — retrieve twice
        memory.get_memories("NIFTY", "access count test", MemoryLayer.SHORT, n=1)
        memory.get_memories("NIFTY", "access count test", MemoryLayer.SHORT, n=1)
        # Assert
        collection = memory._get_collection(MemoryLayer.SHORT)
        result = collection.get(ids=[mem_id])
        assert int(result["metadatas"][0]["access_count"]) >= 1

    def test_importance_and_category_round_trip_across_retrievals(self, memory: TradedMemory) -> None:
        mem_id = memory.add_memory(
            "NIFTY",
            "round-trip signal",
            MemoryLayer.SHORT,
            category="signal",
        )
        collection = memory._get_collection(MemoryLayer.SHORT)
        before = collection.get(ids=[mem_id])["metadatas"][0]

        first = memory.get_memories("NIFTY", "round-trip signal", MemoryLayer.SHORT, n=1)
        second = memory.get_memories("NIFTY", "round-trip signal", MemoryLayer.SHORT, n=1)
        after = collection.get(ids=[mem_id])["metadatas"][0]

        assert first.items[0].importance == pytest.approx(CATEGORY_IMPORTANCE["signal"])
        assert second.items[0].importance == pytest.approx(CATEGORY_IMPORTANCE["signal"])
        assert float(after["importance"]) == pytest.approx(float(before["importance"]))
        assert after["_flinttrade_category"] == "signal"
        assert after["_flinttrade_last_accessed_at"]

    def test_l2_distance_uses_bounded_inverse_conversion(self, memory: TradedMemory) -> None:
        assert memory._distance_to_similarity(0.0) == pytest.approx(1.0)
        assert memory._distance_to_similarity(3.0) == pytest.approx(0.25)

    def test_reopened_collection_uses_its_configured_metric(self, tmp_path) -> None:
        persist_dir = str(tmp_path / "metric")
        prefix = f"metric_{uuid.uuid4().hex[:8]}"
        first = TradedMemory(
            persist_dir=persist_dir,
            collection_prefix=prefix,
            _embedding_fn=_TEST_EMBEDDING_FN,
        )
        collection = first._get_collection(MemoryLayer.SHORT)
        collection.modify(metadata={"hnsw:space": "cosine"})

        memory = TradedMemory(
            persist_dir=persist_dir,
            collection_prefix=prefix,
            _embedding_fn=_TEST_EMBEDDING_FN,
        )
        memory._get_collection(MemoryLayer.SHORT)
        space = memory._distance_spaces[MemoryLayer.SHORT]

        assert space == "cosine"
        assert memory._distance_to_similarity(1.0, space=space) == pytest.approx(0.0)


class TestDifferentLayers:
    """Tests that layers remain separate from each other."""

    def test_different_layers_separate(self, memory: TradedMemory) -> None:
        # Arrange — add a memory to SHORT only
        memory.add_memory("NIFTY", "Short-term NIFTY news signal", MemoryLayer.SHORT)
        # Act — query the LONG layer
        result = memory.get_memories("NIFTY", "NIFTY news signal", MemoryLayer.LONG, n=5)
        # Assert — SHORT memories must NOT appear in LONG queries
        assert result.items == []

    def test_all_four_layers_independent(self, memory: TradedMemory) -> None:
        # Arrange
        for layer in MemoryLayer:
            memory.add_memory("TCS", f"TCS memory in {layer.value}", layer)
        # Act / Assert — each layer has exactly one memory for TCS
        for layer in MemoryLayer:
            result = memory.get_memories("TCS", f"TCS {layer.value}", layer, n=10)
            assert len(result.items) == 1
            assert result.items[0].layer == layer


class _WedgedCollection:
    """Simulates a ChromaDB 1.5.x collection whose vector index is wedged.

    Real behaviour reproduced on chromadb 1.5.9: ``query`` (and any plan
    touching embeddings) permanently raises InternalError "Error finding id",
    while metadata reads (``count``/``get``) and ``update`` keep working.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def count(self) -> int:
        return self._inner.count()

    def query(self, **_kwargs):
        raise RuntimeError("Error executing plan: Internal error: Error finding id")

    def get(self, **kwargs):
        kwargs.pop("limit", None)  # the real client accepts limit; inner pass-through
        return self._inner.get(**kwargs)

    def update(self, **kwargs):
        return self._inner.update(**kwargs)


class TestVectorIndexWedgeFallback:
    """get_memories must survive a wedged vector index via the metadata path.

    Regression for the test_all_four_layers_independent flake: chromadb 1.5.9
    intermittently loses an add()'s embedding write (~4% under rapid collection
    churn), after which every vector query on that collection raises forever
    while plain get() still serves the row. get_memories must degrade to
    metadata retrieval (similarity-neutral ranking), not return nothing.
    """

    def test_wedged_vector_index_falls_back_to_metadata(self, memory: TradedMemory) -> None:
        # Arrange — store two memories, then wedge the collection's vector index
        id_low = memory.add_memory("NIFTY", "low importance wedged memory", MemoryLayer.SHORT)
        id_high = memory.add_memory("NIFTY", "high importance wedged memory", MemoryLayer.SHORT)
        real = memory._get_collection(MemoryLayer.SHORT)
        low_meta = real.get(ids=[id_low])["metadatas"][0]
        high_meta = real.get(ids=[id_high])["metadatas"][0]
        real.update(ids=[id_low], metadatas=[{**low_meta, "importance": 40.0}])
        real.update(ids=[id_high], metadatas=[{**high_meta, "importance": 95.0}])
        memory._collections[MemoryLayer.SHORT] = _WedgedCollection(real)

        # Act
        result = memory.get_memories("NIFTY", "wedged memory", MemoryLayer.SHORT, n=2)

        # Assert — both memories still retrieved via the metadata path, and the
        # similarity-neutral rerank puts the high-importance one first
        assert len(result.items) == 2
        assert result.items[0].id == id_high
        assert {item.id for item in result.items} == {id_low, id_high}

    def test_wedged_vector_index_filters_by_symbol(self, memory: TradedMemory) -> None:
        # Arrange — two symbols in the layer, then wedge it
        memory.add_memory("NIFTY", "NIFTY wedged-path memory", MemoryLayer.MID)
        memory.add_memory("RELIANCE", "RELIANCE wedged-path memory", MemoryLayer.MID)
        real = memory._get_collection(MemoryLayer.MID)
        memory._collections[MemoryLayer.MID] = _WedgedCollection(real)

        # Act
        result = memory.get_memories("NIFTY", "wedged-path", MemoryLayer.MID, n=5)

        # Assert — the metadata fallback still honours the symbol filter
        assert len(result.items) == 1
        assert result.items[0].symbol == "NIFTY"

    def test_metadata_path_also_failing_returns_empty(self, memory: TradedMemory) -> None:
        # Arrange — a collection where BOTH paths raise
        class _FullyBroken:
            @staticmethod
            def count() -> int:
                return 1

            @staticmethod
            def query(**_kwargs):
                raise RuntimeError("Error executing plan: Internal error: Error finding id")

            @staticmethod
            def get(**_kwargs):
                raise RuntimeError("Error executing plan: Internal error: Error finding id")

        memory._collections[MemoryLayer.LONG] = _FullyBroken()

        # Act — must not raise
        result = memory.get_memories("NIFTY", "anything", MemoryLayer.LONG, n=3)

        # Assert — degrades to empty only when even metadata is unreadable
        assert result.items == []


class TestUpdateOnOutcome:
    """Tests for TradedMemory.update_on_outcome."""

    def test_update_on_outcome_correct_increases_importance(self, memory: TradedMemory) -> None:
        # Arrange
        mem_id = memory.add_memory("NIFTY", "NIFTY bullish breakout", MemoryLayer.SHORT)
        collection = memory._get_collection(MemoryLayer.SHORT)
        before = float(collection.get(ids=[mem_id])["metadatas"][0]["importance"])
        # Act
        memory.update_on_outcome([mem_id], direction_correct=True)
        after = float(collection.get(ids=[mem_id])["metadatas"][0]["importance"])
        # Assert
        assert after == pytest.approx(before + 5.0)

    def test_update_on_outcome_incorrect_decreases_importance(self, memory: TradedMemory) -> None:
        # Arrange
        mem_id = memory.add_memory("NIFTY", "NIFTY false breakout", MemoryLayer.MID)
        collection = memory._get_collection(MemoryLayer.MID)
        before = float(collection.get(ids=[mem_id])["metadatas"][0]["importance"])
        # Act
        memory.update_on_outcome([mem_id], direction_correct=False)
        after = float(collection.get(ids=[mem_id])["metadatas"][0]["importance"])
        # Assert
        assert after == pytest.approx(before - 2.0)

    def test_update_on_outcome_importance_never_negative(self, memory: TradedMemory) -> None:
        # Arrange — manually set importance very low
        mem_id = memory.add_memory("NIFTY", "very weak signal", MemoryLayer.SHORT)
        collection = memory._get_collection(MemoryLayer.SHORT)
        meta = collection.get(ids=[mem_id])["metadatas"][0]
        collection.update(ids=[mem_id], metadatas=[{**meta, "importance": 1.0}])
        # Act — weaken many times
        for _ in range(5):
            memory.update_on_outcome([mem_id], direction_correct=False)
        # Assert
        after = float(collection.get(ids=[mem_id])["metadatas"][0]["importance"])
        assert after >= 0.0

    def test_update_on_outcome_unknown_ids_are_ignored(self, memory: TradedMemory) -> None:
        # Act — should not raise
        memory.update_on_outcome(["nonexistent-uuid-1234"], direction_correct=True)


class TestStep:
    """Tests for TradedMemory.step (aging)."""

    def test_step_ages_memories(self, memory: TradedMemory) -> None:
        # Arrange
        mem_id = memory.add_memory("NIFTY", "aging test", MemoryLayer.SHORT)
        collection = memory._get_collection(MemoryLayer.SHORT)
        before = int(collection.get(ids=[mem_id])["metadatas"][0]["recency_delta"])
        # Act
        memory.step(days=3)
        after = int(collection.get(ids=[mem_id])["metadatas"][0]["recency_delta"])
        # Assert
        assert after == before + 3

    def test_step_ages_across_all_layers(self, memory: TradedMemory) -> None:
        # Arrange — one memory per layer
        ids_by_layer = {layer: memory.add_memory("NIFTY", f"step test {layer.value}", layer) for layer in MemoryLayer}
        # Act
        memory.step(days=2)
        # Assert — all layers aged
        for layer, mem_id in ids_by_layer.items():
            collection = memory._get_collection(layer)
            delta = int(collection.get(ids=[mem_id])["metadatas"][0]["recency_delta"])
            assert delta == 2

    def test_step_empty_layer_does_not_crash(self, memory: TradedMemory) -> None:
        # No memories stored; step should be a no-op
        memory.step(days=5)


class TestClearSymbol:
    """Tests for TradedMemory.clear_symbol."""

    def test_clear_symbol_removes_all(self, memory: TradedMemory) -> None:
        # Arrange — add multiple memories across layers for one symbol
        for layer in MemoryLayer:
            memory.add_memory("RELIANCE", f"RELIANCE memory {layer.value}", layer)
        # Act
        memory.clear_symbol("RELIANCE")
        # Assert — all layers empty for RELIANCE
        for layer in MemoryLayer:
            result = memory.get_memories("RELIANCE", "RELIANCE memory", layer, n=10)
            assert result.items == []

    def test_clear_symbol_does_not_remove_other_symbols(self, memory: TradedMemory) -> None:
        # Arrange
        memory.add_memory("NIFTY", "NIFTY should stay", MemoryLayer.SHORT)
        memory.add_memory("TCS", "TCS should be removed", MemoryLayer.SHORT)
        # Act
        memory.clear_symbol("TCS")
        # Assert — NIFTY memory intact
        result = memory.get_memories("NIFTY", "should stay", MemoryLayer.SHORT, n=5)
        assert len(result.items) == 1
        assert result.items[0].symbol == "NIFTY"


class TestPersistentContextAndPruning:
    def test_summarise_context_searches_all_layers_for_symbol(self, memory: TradedMemory) -> None:
        memory.add_memory("NIFTY", "NIFTY breakout signal", MemoryLayer.SHORT, category="signal")
        memory.add_memory("NIFTY", "NIFTY reflection lesson", MemoryLayer.REFLECTION, category="trade")
        memory.add_memory("TCS", "TCS unrelated breakout", MemoryLayer.SHORT, category="signal")

        context = memory.summarise_context("NIFTY", "breakout lesson", max_tokens=200)

        assert context.startswith("[Memory Context]")
        assert "NIFTY breakout signal" in context
        assert "NIFTY reflection lesson" in context
        assert "TCS unrelated breakout" not in context

    def test_prune_supports_score_importance_window_and_symbol_scope(self, memory: TradedMemory) -> None:
        stale_id = memory.add_memory("NIFTY", "stale", MemoryLayer.SHORT)
        weak_id = memory.add_memory("NIFTY", "weak", MemoryLayer.SHORT)
        keep_id = memory.add_memory("NIFTY", "keep", MemoryLayer.SHORT)
        other_id = memory.add_memory("TCS", "other symbol", MemoryLayer.SHORT)
        collection = memory._get_collection(MemoryLayer.SHORT)

        def update(memory_id: str, **values: object) -> None:
            metadata = collection.get(ids=[memory_id])["metadatas"][0]
            collection.update(ids=[memory_id], metadatas=[{**metadata, **values}])

        update(stale_id, recency_delta=90, importance=90.0)
        update(weak_id, recency_delta=0, importance=1.0)
        update(keep_id, recency_delta=0, importance=90.0)
        update(other_id, recency_delta=90, importance=1.0)

        removed = memory.prune(
            min_score=0.05,
            min_importance=0.05,
            max_recency_days=30,
            symbol="NIFTY",
        )

        remaining = set(collection.get()["ids"])
        assert removed == 2
        assert stale_id not in remaining
        assert weak_id not in remaining
        assert keep_id in remaining
        assert other_id in remaining

    def test_clear_common_interface_can_scope_by_symbol(self, memory: TradedMemory) -> None:
        memory.add_memory("NIFTY", "remove", MemoryLayer.SHORT)
        memory.add_memory("TCS", "keep", MemoryLayer.SHORT)

        memory.clear("NIFTY")

        assert memory.get_memories("NIFTY", "remove", MemoryLayer.SHORT).items == []
        assert len(memory.get_memories("TCS", "keep", MemoryLayer.SHORT).items) == 1

    def test_clear_common_interface_removes_every_layer(self, memory: TradedMemory) -> None:
        for layer in MemoryLayer:
            memory.add_memory("NIFTY", f"remove {layer.value}", layer)

        memory.clear()

        for layer in MemoryLayer:
            assert memory._get_collection(layer).count() == 0


class TestMemoryBackendFactory:
    def test_factory_has_runtime_resolvable_protocol_annotation(self) -> None:
        assert get_type_hints(create_memory_backend)["return"] is MemoryBackend

    def test_selects_persistent_backend_from_config(self) -> None:
        backend = create_memory_backend(MemoryBackendConfig(backend=MemoryBackendKind.PERSISTENT, persist_dir=None))
        assert isinstance(backend, TradedMemory)

    def test_selects_hierarchical_backend_from_config(self) -> None:
        backend = create_memory_backend(MemoryBackendConfig(backend=MemoryBackendKind.HIERARCHICAL))
        assert isinstance(backend, HierarchicalMemoryManager)


class TestPersistence:
    """Tests for disk persistence across close/reopen without chromadb."""

    def test_memory_persists_across_instances(self, tmp_path) -> None:
        """Memories written to disk persist across new instances."""
        persist_dir = str(tmp_path / "memory_test")
        os.makedirs(persist_dir, exist_ok=True)

        mem1 = TradedMemory(
            persist_dir=persist_dir,
            collection_prefix="persist_test",
            _embedding_fn=_TEST_EMBEDDING_FN,
        )
        mem_id = mem1.add_memory("NIFTY", "persistent NIFTY memory", MemoryLayer.REFLECTION)
        mem1.add_memory("TCS", "other symbol must not leak", MemoryLayer.REFLECTION)

        mem2 = TradedMemory(
            persist_dir=persist_dir,
            collection_prefix="persist_test",
            _embedding_fn=_TEST_EMBEDDING_FN,
        )
        result = mem2.get_memories("NIFTY", "persistent NIFTY", MemoryLayer.REFLECTION, n=5)

        assert any(item.id == mem_id for item in result.items)
        assert all(item.symbol == "NIFTY" for item in result.items)
