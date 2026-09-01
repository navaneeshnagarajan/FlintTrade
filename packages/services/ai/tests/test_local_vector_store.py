"""Regression tests for FlintTrade's local SQLite/NumPy vector client."""

from __future__ import annotations

import sqlite3

import pytest


def test_query_with_zero_results_returns_empty() -> None:
    """A zero result limit must not turn into an unbounded vector dump."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="ranking")
    collection.add(
        ids=["alpha"],
        documents=["alpha"],
        embeddings=[[1.0, 0.0]],
    )

    result = collection.query(query_embeddings=[[1.0, 0.0]], n_results=0)

    assert result["ids"] == [[]]


def test_persistent_client_refuses_legacy_chroma_without_creating_new_store(tmp_path) -> None:
    """Legacy vectors must remain visible to the operator instead of being shadowed."""
    from flinttrade_ai.local_vector_store import PersistentClient

    legacy_db = tmp_path / "chroma.sqlite3"
    legacy_db.write_bytes(b"legacy-vector-data")

    with pytest.raises(RuntimeError, match="Legacy Chroma vector data detected"):
        PersistentClient(path=str(tmp_path))

    assert legacy_db.read_bytes() == b"legacy-vector-data"
    assert not (tmp_path / "flinttrade_vectors.sqlite").exists()


def test_close_checkpoints_persistent_store_and_is_idempotent(tmp_path) -> None:
    """A clean shutdown leaves a reopenable main database without live WAL state."""
    from flinttrade_ai.local_vector_store import PersistentClient

    client = PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection(name="lifecycle")
    collection.add(ids=["one"], documents=["persist me"], embeddings=[[1.0, 0.0]])

    client.close()
    client.close()

    wal_path = tmp_path / "flinttrade_vectors.sqlite-wal"
    assert not wal_path.exists() or wal_path.stat().st_size == 0

    reopened = PersistentClient(path=str(tmp_path))
    try:
        assert reopened.get_or_create_collection(name="lifecycle").count() == 1
    finally:
        reopened.close()


def test_multi_item_add_rolls_back_as_one_transaction() -> None:
    """A duplicate in one batch must not leave a partially persisted prefix."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="atomic")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        collection.add(
            ids=["duplicate", "duplicate"],
            documents=["first", "second"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
        )

    assert collection.count() == 0


def test_multi_item_update_rolls_back_as_one_transaction() -> None:
    """A serialization failure must not leave an earlier row partially updated."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="atomic-update")
    collection.add(
        ids=["one", "two"],
        documents=["original one", "original two"],
        metadatas=[{"version": 1}, {"version": 1}],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
    )

    with pytest.raises((TypeError, ValueError)):
        collection.update(
            ids=["one", "two"],
            documents=["changed one", "changed two"],
            metadatas=[{"version": 2}, {"version": 2}],
            embeddings=[[2.0, 0.0], [object()]],
        )

    result = collection.get(ids=["one", "two"], include=["documents", "metadatas"])
    assert result["documents"] == ["original one", "original two"]
    assert result["metadatas"] == [{"version": 1}, {"version": 1}]
