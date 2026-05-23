"""Tests for TradedMemory — 4-layer ChromaDB-backed trading memory system.

All tests use an in-memory ChromaDB EphemeralClient so no disk I/O occurs.
Each test gets a unique collection_prefix (via uuid4) so that the shared
EphemeralClient's in-memory state does not bleed between tests.
"""

from __future__ import annotations

import math
import os
import uuid

import numpy as np
import pytest

chromadb = pytest.importorskip("chromadb", reason="chromadb not installed")

from flinttrade_ai.memory import (  # noqa: E402 — must follow chromadb importorskip
    MemoryLayer,
    MemoryQueryResult,
    TradedMemory,
    compound_score,
    exponential_decay,
    initial_importance,
)

# One EphemeralClient shared across the process (ChromaDB requirement).
# Test isolation is achieved via unique collection_prefix per test.
_EPHEMERAL_CLIENT = chromadb.EphemeralClient()


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
        return ["l2"]

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
        _chroma_client=_EPHEMERAL_CLIENT,
        _embedding_fn=_TEST_EMBEDDING_FN,
    )
    defaults.update(kwargs)
    return TradedMemory(**defaults)


@pytest.fixture
def memory() -> TradedMemory:
    """Fresh isolated TradedMemory instance for each test."""
    return make_memory()


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
                assert lo <= value <= hi, (
                    f"{layer.value} importance {value:.2f} outside [{lo}, {hi}]"
                )

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
            assert lo <= importance <= hi, (
                f"{layer.value}: importance {importance:.2f} outside [{lo}, {hi}]"
            )


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
        ids_by_layer = {
            layer: memory.add_memory("NIFTY", f"step test {layer.value}", layer)
            for layer in MemoryLayer
        }
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


class TestPersistence:
    """Tests for PersistentClient across instances."""

    def test_memory_persists_across_instances(self, tmp_path) -> None:
        """Memories written to a PersistentClient persist across new instances."""
        # Arrange — write to a real PersistentClient in a temp directory
        persist_dir = str(tmp_path / "chroma_test")
        os.makedirs(persist_dir, exist_ok=True)

        mem1 = TradedMemory(
            persist_dir=persist_dir,
            collection_prefix="persist_test",
            _embedding_fn=_TEST_EMBEDDING_FN,
        )
        mem_id = mem1.add_memory("NIFTY", "persistent NIFTY memory", MemoryLayer.REFLECTION)

        # Act — create a second instance pointing at the same directory
        mem2 = TradedMemory(
            persist_dir=persist_dir,
            collection_prefix="persist_test",
            _embedding_fn=_TEST_EMBEDDING_FN,
        )
        # Force the collection to re-open (lazy init)
        result = mem2.get_memories("NIFTY", "persistent NIFTY", MemoryLayer.REFLECTION, n=5)

        # Assert — memory created in mem1 is visible in mem2
        assert any(item.id == mem_id for item in result.items)
