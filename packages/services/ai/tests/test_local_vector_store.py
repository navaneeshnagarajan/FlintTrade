"""Regression tests for FlintTrade's local SQLite/NumPy vector client."""

from __future__ import annotations

import sqlite3

import pytest


def test_hashing_embedder_does_not_emit_zero_vectors_on_sign_cancellation() -> None:
    """Cancelled hash buckets must still yield a unit vector so identical text matches."""
    import numpy as np

    from flinttrade_ai.local_vector_store import HashingEmbeddingFunction, _distance

    embedder = HashingEmbeddingFunction()
    stored = embedder("support momentum")[0]
    query = embedder("support momentum")[0]

    assert float(np.linalg.norm(stored)) == pytest.approx(1.0)
    assert _distance("cosine", stored, query) == pytest.approx(0.0)


def test_hashing_collision_fallback_uses_canonical_tokens() -> None:
    """Case, punctuation, and extra whitespace must share one fallback bucket."""
    import numpy as np

    from flinttrade_ai.local_vector_store import HashingEmbeddingFunction, _distance

    embedder = HashingEmbeddingFunction()
    canonical = embedder("support momentum")[0]
    variants = [
        embedder("Support momentum")[0],
        embedder("support  momentum")[0],
        embedder("support momentum!")[0],
    ]

    assert float(np.linalg.norm(canonical)) == pytest.approx(1.0)
    for variant in variants:
        assert _distance("cosine", canonical, variant) == pytest.approx(0.0)


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


def test_empty_collection_adopts_first_embedding_dimension() -> None:
    """The first write pins the collection dimension; later sizes are refused."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="dim")
    collection.add(ids=["first"], documents=["seed"], embeddings=[[1.0, 0.0, 0.0]])

    with pytest.raises(ValueError, match="3-dimensional"):
        collection.add(ids=["second"], documents=["too wide"], embeddings=[[1.0, 0.0]])

    assert collection.count() == 1
    assert client._known_embedding_dim("dim") == 3


def test_reopened_collection_rejects_mismatched_embedding_dimension(tmp_path) -> None:
    """A persisted dimension must survive close/reopen and block mixed writes."""
    from flinttrade_ai.local_vector_store import PersistentClient

    original = PersistentClient(path=str(tmp_path))
    try:
        collection = original.get_or_create_collection(name="rag")
        collection.add(ids=["a"], documents=["narrow"], embeddings=[[1.0, 0.0]])
    finally:
        original.close()

    reopened = PersistentClient(path=str(tmp_path))
    try:
        collection = reopened.get_or_create_collection(name="rag")
        with pytest.raises(ValueError, match="2-dimensional"):
            collection.add(
                ids=["b"],
                documents=["wide"],
                embeddings=[[1.0] * 4],
            )
        assert collection.count() == 1
        result = collection.query(query_embeddings=[[1.0, 0.0]], n_results=1)
        assert result["ids"] == [["a"]]
    finally:
        reopened.close()


def test_mixed_dimension_batch_is_rejected_as_one_transaction() -> None:
    """A single batch must not commit a prefix of mixed-width vectors."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="batch-dim")

    with pytest.raises(ValueError, match="share one dimension"):
        collection.add(
            ids=["narrow", "wide"],
            documents=["ok", "bad"],
            embeddings=[[1.0, 0.0], [1.0, 0.0, 0.0, 0.0]],
        )

    assert collection.count() == 0
    assert client._known_embedding_dim("batch-dim") is None
    collection.add(
        ids=["valid"],
        documents=["valid three-dimensional vector"],
        embeddings=[[1.0, 0.0, 0.0]],
    )
    assert collection.count() == 1
    assert client._known_embedding_dim("batch-dim") == 3
    client.close()


def test_persistent_client_migrates_pre_dimension_collection_schema(tmp_path) -> None:
    """Existing local-store files gain the dimension column without losing collections."""
    from flinttrade_ai.local_vector_store import PersistentClient

    db_path = tmp_path / "flinttrade_vectors.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE collections (
            name TEXT PRIMARY KEY,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            space TEXT NOT NULL DEFAULT 'l2'
        )
        """
    )
    connection.execute(
        "INSERT INTO collections(name, metadata_json, space) VALUES (?, ?, ?)",
        ("existing", "{}", "l2"),
    )
    connection.commit()
    connection.close()

    client = PersistentClient(path=str(tmp_path))
    try:
        collection = client.get_or_create_collection(name="existing")
        collection.add(
            ids=["kept"],
            documents=["kept after schema migration"],
            embeddings=[[1.0, 0.0]],
        )
        assert collection.count() == 1
    finally:
        client.close()


def test_legacy_schema_infers_and_persists_collection_dimension(tmp_path) -> None:
    """Stores created before embedding_dim still pin the inferred width."""
    from flinttrade_ai.local_vector_store import PersistentClient, _dump_embedding

    db_path = tmp_path / "flinttrade_vectors.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE collections (
            name TEXT PRIMARY KEY,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            space TEXT NOT NULL DEFAULT 'l2'
        );
        CREATE TABLE items (
            collection TEXT NOT NULL,
            id TEXT NOT NULL,
            document TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            embedding BLOB,
            PRIMARY KEY (collection, id)
        );
        """
    )
    conn.execute(
        "INSERT INTO collections (name, metadata_json, space) VALUES (?, ?, ?)",
        ("legacy", "{}", "cosine"),
    )
    conn.execute(
        "INSERT INTO items (collection, id, document, metadata_json, embedding) VALUES (?, ?, ?, ?, ?)",
        ("legacy", "kept", "old row", "{}", _dump_embedding([1.0, 0.0])),
    )
    conn.commit()
    conn.close()

    client = PersistentClient(path=str(tmp_path))
    try:
        collection = client.get_or_create_collection(name="legacy")
        with pytest.raises(ValueError, match="2-dimensional"):
            collection.add(ids=["new"], documents=["wide"], embeddings=[[0.0] * 8])
        assert collection.count() == 1
        assert client._known_embedding_dim("legacy") == 2
    finally:
        client.close()


def test_query_rejects_mismatched_embedding_dimension() -> None:
    """A pinned collection must not silently skip every row on a width change."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="query-dim")
    collection.add(ids=["kept"], documents=["narrow"], embeddings=[[1.0, 0.0]])

    with pytest.raises(ValueError, match="2-dimensional"):
        collection.query(query_embeddings=[[1.0, 0.0, 0.0, 0.0]], n_results=1)

    result = collection.query(query_embeddings=[[1.0, 0.0]], n_results=1)
    assert result["ids"] == [["kept"]]
    client.close()


def test_reopened_collection_rejects_mismatched_query_dimension(tmp_path) -> None:
    """A persisted width must fail closed on query after the embedding model changes."""
    from flinttrade_ai.local_vector_store import PersistentClient

    original = PersistentClient(path=str(tmp_path))
    try:
        collection = original.get_or_create_collection(name="rag")
        collection.add(ids=["a"], documents=["narrow"], embeddings=[[1.0, 0.0]])
    finally:
        original.close()

    reopened = PersistentClient(path=str(tmp_path))
    try:
        collection = reopened.get_or_create_collection(name="rag")
        with pytest.raises(ValueError, match="2-dimensional"):
            collection.query(query_embeddings=[[0.0] * 8], n_results=1)
        result = collection.query(query_embeddings=[[1.0, 0.0]], n_results=1)
        assert result["ids"] == [["a"]]
    finally:
        reopened.close()


def test_empty_embedding_is_rejected_without_pinning_collection() -> None:
    """Zero-dimensional vectors cannot establish a collection's schema."""
    from flinttrade_ai.local_vector_store import EphemeralClient

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="empty")

    with pytest.raises(ValueError, match="must not be empty"):
        collection.add(
            ids=["empty"],
            documents=["invalid"],
            embeddings=[[]],
        )

    assert collection.count() == 0
    assert client._known_embedding_dim("empty") is None
    client.close()


def test_l2_distance_is_squared_euclidean() -> None:
    """Default/l2 ranking must match Chroma HNSW squared Euclidean, not the L2 norm."""
    import numpy as np

    from flinttrade_ai.local_vector_store import EphemeralClient, _distance

    left = np.array([1.0, 0.0], dtype=np.float32)
    right = np.array([0.0, 1.0], dtype=np.float32)
    assert _distance("l2", left, right) == pytest.approx(2.0)
    assert _distance("cosine", left, right) == pytest.approx(1.0)

    unit_a = np.array([1.0, 0.0], dtype=np.float32)
    unit_b = np.array([0.6, 0.8], dtype=np.float32)
    squared = _distance("l2", unit_a, unit_b)
    cosine_sim = 1.0 - _distance("cosine", unit_a, unit_b)
    assert 1.0 - (squared / 2.0) == pytest.approx(cosine_sim)

    client = EphemeralClient()
    collection = client.get_or_create_collection(name="l2", metadata={"hnsw:space": "l2"})
    collection.add(
        ids=["orthogonal"],
        documents=["unit orthogonal"],
        embeddings=[[0.0, 1.0]],
    )
    hits = collection.query(query_embeddings=[[1.0, 0.0]], n_results=1)
    assert hits["distances"][0][0] == pytest.approx(2.0)
    client.close()


def test_inner_product_distance_does_not_normalise_operands() -> None:
    """Inner-product ranking must keep magnitude; cosine still uses unit similarity."""
    import numpy as np

    from flinttrade_ai.local_vector_store import EphemeralClient, _distance

    left = np.array([2.0, 0.0], dtype=np.float32)
    right = np.array([2.0, 0.0], dtype=np.float32)
    assert _distance("ip", left, right) == pytest.approx(1.0 - 4.0)
    assert _distance("inner_product", left, right) == pytest.approx(1.0 - 4.0)
    assert _distance("cosine", left, right) == pytest.approx(0.0)

    client = EphemeralClient()
    cosine = client.get_or_create_collection(name="cosine", metadata={"hnsw:space": "cosine"})
    inner = client.get_or_create_collection(name="ip", metadata={"hnsw:space": "ip"})
    ids = ["a-short", "b-long"]
    documents = ["short", "long"]
    embeddings = [[1.0, 0.0], [3.0, 0.0]]
    cosine.add(ids=ids, documents=documents, embeddings=embeddings)
    inner.add(ids=ids, documents=documents, embeddings=embeddings)

    cosine_hits = cosine.query(query_embeddings=[[2.0, 0.0]], n_results=2)
    inner_hits = inner.query(query_embeddings=[[2.0, 0.0]], n_results=2)

    assert cosine_hits["ids"][0][0] == "a-short"
    assert inner_hits["ids"][0][0] == "b-long"
