"""Local sqlite3 + numpy vector store used by TradedMemory and VectorStore.

This replaces ChromaDB persistence with a process-local, no-server backend.
Embeddings are stored on disk so a reopen does not re-index. Ranking is
deterministic (distance, then id). No network model downloads occur.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("flinttrade.ai.local_vector_store")

_DB_NAME = "flinttrade_vectors.sqlite"
_LEGACY_CHROMA_DB_NAME = "chroma.sqlite3"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DEFAULT_DIM = 64
_VALID_SPACES = {"cosine", "l2", "ip", "inner_product"}


class LegacyChromaStoreDetectedError(RuntimeError):
    """Raised before a new store can shadow preserved legacy Chroma vectors."""


def assert_no_legacy_chroma_store(path: str | Path) -> None:
    """Refuse to create an empty local store beside unread legacy Chroma data."""
    directory = Path(os.path.expanduser(str(path)))
    if (directory / _LEGACY_CHROMA_DB_NAME).exists():
        raise LegacyChromaStoreDetectedError(
            "Legacy Chroma vector data detected. FlintTrade left it untouched and "
            "refused to create a replacement store in the same directory. Export it "
            "with the previous release, or move the complete legacy directory aside "
            "after explicitly accepting an empty new store."
        )


class HashingEmbeddingFunction:
    """Deterministic hashing embedder. No model download, no network."""

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self._dim = dim

    @staticmethod
    def name() -> str:
        return "flinttrade-hashing"

    @staticmethod
    def default_space() -> str:
        return "cosine"

    def __call__(self, input: str | list[str]) -> list[np.ndarray]:
        documents = [input] if isinstance(input, str) else list(input)
        return [self._embed(str(document)) for document in documents]

    def _embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dim, dtype=np.float32)
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            vec[0] = 1.0
            return vec
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec /= norm
            return vec
        # Opposite signs in the same buckets can cancel to zero. Keep a
        # deterministic unit vector so an identical query still matches.
        # Hash the same token stream the buckets used, not the raw text —
        # otherwise case, punctuation, or extra whitespace pick a different
        # fallback bucket for the same tokens.
        digest = hashlib.blake2b(" ".join(tokens).encode("utf-8"), digest_size=8).digest()
        vec[int.from_bytes(digest[:4], "little") % self._dim] = 1.0
        return vec


def _as_float32(vector: Any) -> np.ndarray:
    return np.asarray(vector, dtype=np.float32).reshape(-1)


def _vector_dim(vector: Any | None) -> int | None:
    """Return the float32 length of a stored or incoming embedding."""
    if vector is None:
        return None
    if isinstance(vector, (bytes, bytearray)):
        if len(vector) % 4 != 0:
            raise ValueError("embedding blob is not float32-aligned")
        dim = len(vector) // 4
        if dim == 0:
            raise ValueError("embedding must not be empty")
        return dim
    arr = _as_float32(vector)
    if arr.size == 0:
        raise ValueError("embedding must not be empty")
    return int(arr.size)


def _batch_embedding_dim(embeddings: list[Any] | None) -> int | None:
    """Return the one dimension shared by a write batch, or None if none present."""
    if not embeddings:
        return None
    resolved: int | None = None
    for embedding in embeddings:
        dim = _vector_dim(embedding)
        if dim is None:
            continue
        if resolved is None:
            resolved = dim
        elif dim != resolved:
            raise ValueError(
                f"embeddings in one write must share one dimension; got {resolved} and {dim}"
            )
    return resolved


def _dump_embedding(vector: Any | None) -> bytes | None:
    if vector is None:
        return None
    return _as_float32(vector).tobytes()


def _load_embedding(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32).copy()


def _dump_metadata(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, default=str, sort_keys=True)


def _load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


def _space_from_spec(
    metadata: dict[str, Any] | None,
    configuration: dict[str, Any] | None,
    embedding_fn: Any | None,
) -> str:
    if isinstance(configuration, dict):
        for index_name in ("hnsw", "spann"):
            index_config = configuration.get(index_name)
            if isinstance(index_config, dict) and index_config.get("space"):
                return str(index_config["space"]).lower()
    if isinstance(metadata, dict):
        for key in ("flinttrade_distance_space", "hnsw:space"):
            if metadata.get(key):
                return str(metadata[key]).lower()
    default_space = getattr(embedding_fn, "default_space", None) if embedding_fn is not None else None
    space = default_space() if callable(default_space) else default_space
    space_value = getattr(space, "value", space)
    if space_value:
        return str(space_value).lower()
    return "l2"


def _match_where(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    if "$and" in where:
        clauses = where["$and"]
        return isinstance(clauses, list) and all(_match_where(metadata, clause) for clause in clauses)
    if "$or" in where:
        clauses = where["$or"]
        return isinstance(clauses, list) and any(_match_where(metadata, clause) for clause in clauses)
    for key, expected in where.items():
        if key.startswith("$"):
            continue
        actual = metadata.get(key)
        if isinstance(expected, dict):
            if "$eq" in expected and actual != expected["$eq"]:
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _distance(space: str, left: np.ndarray, right: np.ndarray) -> float:
    """Return a Chroma-compatible distance for one stored metric.

    Default and ``l2`` are *squared* Euclidean — the HNSW ``l2`` space the
    replaced Chroma store used. RAG then maps that with ``1 - dist / 2``,
    which recovers cosine similarity on unit vectors. Cosine alone
    normalises; ``ip`` / ``inner_product`` keep magnitude.
    """
    resolved = space.lower()
    if resolved in {"ip", "inner_product"}:
        return 1.0 - float(np.dot(left, right))
    if resolved == "cosine":
        left_norm = float(np.linalg.norm(left))
        right_norm = float(np.linalg.norm(right))
        if left_norm == 0.0 or right_norm == 0.0:
            similarity = 0.0
        else:
            similarity = float(np.dot(left, right) / (left_norm * right_norm))
        return 1.0 - similarity
    diff = left - right
    return float(np.dot(diff, diff))


class Collection:
    """Chroma-compatible collection backed by sqlite3."""

    def __init__(
        self,
        client: LocalVectorClient,
        name: str,
        *,
        metadata: dict[str, Any] | None,
        space: str,
        embedding_function: Any | None,
    ) -> None:
        self._client = client
        self._name = name
        self._metadata = dict(metadata or {})
        self._space = space if space in _VALID_SPACES else "l2"
        self._embedding_fn = embedding_function

    @property
    def name(self) -> str:
        return self._name

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    @property
    def configuration(self) -> dict[str, Any]:
        return {"hnsw": {"space": self._space}}

    def count(self) -> int:
        return self._client._count(self._name)

    def add(
        self,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
        embeddings: list[Any] | None = None,
    ) -> None:
        self._write(ids, documents, metadatas, embeddings, replace=False)

    def upsert(
        self,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
        embeddings: list[Any] | None = None,
    ) -> None:
        self._write(ids, documents, metadatas, embeddings, replace=True)

    def update(
        self,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
        embeddings: list[Any] | None = None,
    ) -> None:
        self._client._update(
            self._name,
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def delete(self, ids: list[str] | None = None, where: dict[str, Any] | None = None) -> None:
        self._client._delete(self._name, ids=ids, where=where)

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        rows = self._client._fetch(self._name, ids=ids, where=where, limit=limit)
        return self._format_get(rows, include)

    def query(
        self,
        query_texts: list[str] | None = None,
        query_embeddings: list[Any] | None = None,
        n_results: int = 10,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        vectors = self._query_vectors(query_texts, query_embeddings)
        self._enforce_query_dim(vectors)
        rows = self._client._fetch(self._name, where=where)
        nested_ids: list[list[str]] = []
        nested_documents: list[list[str | None]] = []
        nested_metadatas: list[list[dict[str, Any]]] = []
        nested_distances: list[list[float]] = []
        include_fields = include if include is not None else ["documents", "metadatas", "distances"]
        for vector in vectors:
            ranked = self._rank(rows, vector, n_results)
            nested_ids.append([item_id for item_id, _row, _dist in ranked])
            nested_documents.append([row["document"] for _item_id, row, _dist in ranked])
            nested_metadatas.append([row["metadata"] for _item_id, row, _dist in ranked])
            nested_distances.append([dist for _item_id, _row, dist in ranked])
        result: dict[str, Any] = {"ids": nested_ids}
        if "documents" in include_fields:
            result["documents"] = nested_documents
        if "metadatas" in include_fields:
            result["metadatas"] = nested_metadatas
        if "distances" in include_fields:
            result["distances"] = nested_distances
        return result

    def modify(self, metadata: dict[str, Any] | None = None) -> None:
        if metadata is None:
            return
        self._metadata = dict(metadata)
        space = _space_from_spec(self._metadata, None, None)
        if space in _VALID_SPACES:
            self._space = space
        self._client._save_collection(self._name, self._metadata, self._space)

    def _write(
        self,
        ids: list[str],
        documents: list[str] | None,
        metadatas: list[dict[str, Any]] | None,
        embeddings: list[Any] | None,
        *,
        replace: bool,
    ) -> None:
        docs = list(documents) if documents is not None else [""] * len(ids)
        metas = list(metadatas) if metadatas is not None else [{} for _ in ids]
        if len(docs) != len(ids) or len(metas) != len(ids):
            raise ValueError("ids, documents, and metadatas must be the same length")
        resolved_embeddings = embeddings
        if resolved_embeddings is None:
            resolved_embeddings = self._embed(docs)
        if len(resolved_embeddings) != len(ids):
            raise ValueError("embeddings must match ids")
        self._client._insert(
            self._name,
            ids=ids,
            documents=docs,
            metadatas=metas,
            embeddings=resolved_embeddings,
            replace=replace,
        )

    def _embed(self, texts: list[str]) -> list[np.ndarray]:
        embedding_fn = self._embedding_fn or HashingEmbeddingFunction()
        self._embedding_fn = embedding_fn
        raw = embedding_fn(texts)
        return [_as_float32(vector) for vector in raw]

    def _enforce_query_dim(self, vectors: list[np.ndarray]) -> None:
        expected_dim = self._client._known_embedding_dim(self._name)
        if expected_dim is None:
            return
        for vector in vectors:
            query_dim = int(vector.size)
            if query_dim != expected_dim:
                raise ValueError(
                    f"collection '{self._name}' stores {expected_dim}-dimensional embeddings; "
                    f"refusing a {query_dim}-dimensional query"
                )

    def _query_vectors(
        self,
        query_texts: list[str] | None,
        query_embeddings: list[Any] | None,
    ) -> list[np.ndarray]:
        if query_embeddings is not None:
            return [_as_float32(vector) for vector in query_embeddings]
        if query_texts is not None:
            return self._embed(list(query_texts))
        return []

    def _rank(
        self,
        rows: list[dict[str, Any]],
        query: np.ndarray,
        n_results: int,
    ) -> list[tuple[str, dict[str, Any], float]]:
        query_dim = int(query.size)
        scored: list[tuple[str, dict[str, Any], float]] = []
        for row in rows:
            embedding = row["embedding"]
            if embedding is None or int(embedding.size) != query_dim:
                continue
            scored.append((row["id"], row, _distance(self._space, query, embedding)))
        scored.sort(key=lambda item: (item[2], item[0]))
        limit = max(0, n_results)
        return scored[:limit]

    @staticmethod
    def _format_get(rows: list[dict[str, Any]], include: list[str] | None) -> dict[str, Any]:
        fields = include if include is not None else ["documents", "metadatas"]
        result: dict[str, Any] = {"ids": [row["id"] for row in rows]}
        if "documents" in fields:
            result["documents"] = [row["document"] for row in rows]
        if "metadatas" in fields:
            result["metadatas"] = [row["metadata"] for row in rows]
        if "embeddings" in fields:
            result["embeddings"] = [row["embedding"].tolist() if row["embedding"] is not None else None for row in rows]
        return result


class LocalVectorClient:
    """Process-local vector client. Persistent when ``path`` is set."""

    def __init__(self, path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._collections: dict[str, Collection] = {}
        self._persistent = bool(path)
        self._closed = False
        if path:
            directory = Path(os.path.expanduser(path))
            assert_no_legacy_chroma_store(directory)
            directory.mkdir(parents=True, exist_ok=True)
            db_path = str(directory / _DB_NAME)
            self._conn = sqlite3.connect(
                db_path,
                isolation_level=None,
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.execute("PRAGMA foreign_keys = ON")
        else:
            self._conn = sqlite3.connect(
                ":memory:",
                isolation_level=None,
                check_same_thread=False,
            )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        """Checkpoint persistent WAL state and close the SQLite connection once."""
        with self._lock:
            if self._closed:
                return
            try:
                if self._persistent:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self._conn.close()
                self._closed = True
                self._collections.clear()

    def __enter__(self) -> LocalVectorClient:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def get_or_create_collection(
        self,
        name: str,
        embedding_function: Any | None = None,
        metadata: dict[str, Any] | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> Collection:
        with self._lock:
            existing = self._load_collection_row(name)
            if existing is not None:
                stored_metadata, stored_space, _stored_dim = existing
                collection = Collection(
                    self,
                    name,
                    metadata=stored_metadata,
                    space=stored_space,
                    embedding_function=embedding_function,
                )
                self._collections[name] = collection
                return collection
            space = _space_from_spec(metadata, configuration, embedding_function)
            stored_metadata = dict(metadata or {})
            if "hnsw:space" not in stored_metadata:
                stored_metadata["hnsw:space"] = space
            self._save_collection(name, stored_metadata, space)
            collection = Collection(
                self,
                name,
                metadata=stored_metadata,
                space=space,
                embedding_function=embedding_function,
            )
            self._collections[name] = collection
            return collection

    def delete_collection(self, name: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM items WHERE collection = ?", (name,))
            self._conn.execute("DELETE FROM collections WHERE name = ?", (name,))
            self._collections.pop(name, None)

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collections (
                    name TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    space TEXT NOT NULL DEFAULT 'l2',
                    embedding_dim INTEGER
                );
                CREATE TABLE IF NOT EXISTS items (
                    collection TEXT NOT NULL,
                    id TEXT NOT NULL,
                    document TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    embedding BLOB,
                    PRIMARY KEY (collection, id),
                    FOREIGN KEY (collection) REFERENCES collections(name) ON DELETE CASCADE
                );
                """
            )
            columns = {
                str(row["name"]) for row in self._conn.execute("PRAGMA table_info(collections)")
            }
            if "embedding_dim" not in columns:
                self._conn.execute("ALTER TABLE collections ADD COLUMN embedding_dim INTEGER")

    def _load_collection_row(self, name: str) -> tuple[dict[str, Any], str, int | None] | None:
        row = self._conn.execute(
            "SELECT metadata_json, space, embedding_dim FROM collections WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        dim = self._known_embedding_dim(name)
        return _load_metadata(row["metadata_json"]), str(row["space"]).lower(), dim

    def _infer_embedding_dim(self, name: str) -> int | None:
        rows = self._conn.execute(
            "SELECT embedding FROM items WHERE collection = ? AND embedding IS NOT NULL",
            (name,),
        ).fetchall()
        resolved: int | None = None
        for row in rows:
            dim = _vector_dim(row["embedding"])
            if dim is None:
                continue
            if resolved is None:
                resolved = dim
            elif dim != resolved:
                raise ValueError(
                    f"collection '{name}' contains mixed embedding dimensions: "
                    f"{resolved} and {dim}"
                )
        return resolved

    def _known_embedding_dim(self, name: str) -> int | None:
        row = self._conn.execute(
            "SELECT embedding_dim FROM collections WHERE name = ?",
            (name,),
        ).fetchone()
        if row is not None and row["embedding_dim"] is not None:
            return int(row["embedding_dim"])
        inferred = self._infer_embedding_dim(name)
        if inferred is not None:
            self._conn.execute(
                "UPDATE collections SET embedding_dim = ? WHERE name = ? AND embedding_dim IS NULL",
                (inferred, name),
            )
        return inferred

    def _set_embedding_dim(self, name: str, dim: int) -> None:
        self._conn.execute(
            "UPDATE collections SET embedding_dim = ? WHERE name = ?",
            (dim, name),
        )

    def _enforce_embedding_dim(self, name: str, embeddings: list[Any] | None) -> None:
        batch_dim = _batch_embedding_dim(embeddings)
        expected_dim = self._known_embedding_dim(name)
        if expected_dim is not None and batch_dim is not None and expected_dim != batch_dim:
            raise ValueError(
                f"collection '{name}' stores {expected_dim}-dimensional embeddings; "
                f"refusing a {batch_dim}-dimensional write"
            )
        if expected_dim is None and batch_dim is not None:
            self._set_embedding_dim(name, batch_dim)

    def _save_collection(self, name: str, metadata: dict[str, Any], space: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO collections (name, metadata_json, space, embedding_dim)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(name) DO UPDATE SET
                    metadata_json = excluded.metadata_json,
                    space = excluded.space
                """,
                (name, _dump_metadata(metadata), space),
            )

    def _count(self, name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM items WHERE collection = ?",
                (name,),
            ).fetchone()
            return int(row["n"] if row is not None else 0)

    def _insert(
        self,
        name: str,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[Any],
        replace: bool,
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._enforce_embedding_dim(name, embeddings)
                for item_id, document, metadata, embedding in zip(
                    ids, documents, metadatas, embeddings, strict=True
                ):
                    payload = (
                        name,
                        item_id,
                        document,
                        _dump_metadata(metadata),
                        _dump_embedding(embedding),
                    )
                    if replace:
                        self._conn.execute(
                            """
                            INSERT INTO items (collection, id, document, metadata_json, embedding)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(collection, id) DO UPDATE SET
                                document = excluded.document,
                                metadata_json = excluded.metadata_json,
                                embedding = excluded.embedding
                            """,
                            payload,
                        )
                    else:
                        self._conn.execute(
                            """
                            INSERT INTO items (collection, id, document, metadata_json, embedding)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            payload,
                        )
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _update(
        self,
        name: str,
        *,
        ids: list[str],
        documents: list[str] | None,
        metadatas: list[dict[str, Any]] | None,
        embeddings: list[Any] | None,
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                applied: list[tuple[str, Any, Any, Any]] = []
                applied_embeddings: list[Any] = []
                for index, item_id in enumerate(ids):
                    row = self._conn.execute(
                        "SELECT document, metadata_json, embedding FROM items WHERE collection = ? AND id = ?",
                        (name, item_id),
                    ).fetchone()
                    if row is None:
                        continue
                    document = documents[index] if documents is not None else row["document"]
                    metadata = (
                        metadatas[index] if metadatas is not None else _load_metadata(row["metadata_json"])
                    )
                    embedding = embeddings[index] if embeddings is not None else row["embedding"]
                    applied.append((item_id, document, metadata, embedding))
                    if embeddings is not None:
                        applied_embeddings.append(embeddings[index])
                # Pin or reject width only for embeddings that will actually
                # land on an existing row. A no-op update of missing IDs must
                # not freeze an empty collection to the caller's dimension.
                if applied_embeddings:
                    self._enforce_embedding_dim(name, applied_embeddings)
                for item_id, document, metadata, embedding in applied:
                    blob = embedding if isinstance(embedding, (bytes, bytearray)) else _dump_embedding(embedding)
                    self._conn.execute(
                        """
                        UPDATE items
                        SET document = ?, metadata_json = ?, embedding = ?
                        WHERE collection = ? AND id = ?
                        """,
                        (document, _dump_metadata(metadata), blob, name, item_id),
                    )
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _delete(
        self,
        name: str,
        *,
        ids: list[str] | None,
        where: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._fetch(name, ids=ids, where=where)
                if rows:
                    self._conn.executemany(
                        "DELETE FROM items WHERE collection = ? AND id = ?",
                        [(name, row["id"]) for row in rows],
                    )
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _fetch(
        self,
        name: str,
        *,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            sql = "SELECT id, document, metadata_json, embedding FROM items WHERE collection = ?"
            params: list[Any] = [name]
            if ids is not None:
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                sql += f" AND id IN ({placeholders})"
                params.extend(ids)
            sql += " ORDER BY id"
            rows = self._conn.execute(sql, params).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            metadata = _load_metadata(row["metadata_json"])
            if not _match_where(metadata, where):
                continue
            items.append(
                {
                    "id": row["id"],
                    "document": row["document"],
                    "metadata": metadata,
                    "embedding": _load_embedding(row["embedding"]),
                }
            )
            if limit is not None and len(items) >= limit:
                break
        return items


class PersistentClient(LocalVectorClient):
    """Disk-backed client. ``path`` is a directory, matching Chroma's constructor."""

    def __init__(self, path: str) -> None:
        super().__init__(path=path)


class EphemeralClient(LocalVectorClient):
    """In-memory client used when no persist directory is configured."""

    def __init__(self) -> None:
        super().__init__(path=None)


Client = EphemeralClient
