"""RAG startup controls."""

from __future__ import annotations

import logging
import sys
import threading
from types import SimpleNamespace

from flinttrade_ai.llm_client import LLMConfig
from flinttrade_ai.rag_pipeline import RAGPipeline

from flinttrade_core import app as app_module


def test_rag_auto_index_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FLINTTRADE_RAG_AUTO_INDEX", raising=False)

    assert app_module._rag_auto_index_enabled() is False


def test_rag_auto_index_enabled_by_explicit_flag(monkeypatch) -> None:
    monkeypatch.setenv("FLINTTRADE_RAG_AUTO_INDEX", "true")

    assert app_module._rag_auto_index_enabled() is True


def test_rag_runtime_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FLINTTRADE_RAG_ENABLED", raising=False)
    monkeypatch.delenv("FLINTTRADE_RAG_AUTO_INDEX", raising=False)

    assert app_module._rag_runtime_enabled() is False


def test_rag_runtime_enabled_by_explicit_flag(monkeypatch) -> None:
    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "yes")
    monkeypatch.delenv("FLINTTRADE_RAG_AUTO_INDEX", raising=False)

    assert app_module._rag_runtime_enabled() is True


def test_rag_runtime_enabled_when_auto_index_enabled(monkeypatch) -> None:
    monkeypatch.delenv("FLINTTRADE_RAG_ENABLED", raising=False)
    monkeypatch.setenv("FLINTTRADE_RAG_AUTO_INDEX", "1")

    assert app_module._rag_runtime_enabled() is True


def test_rag_background_indexer_logs_failures(caplog) -> None:
    class BrokenRag:
        def index_directory(self, _path: str) -> int:
            raise RuntimeError("embedding cache unavailable")

    caplog.set_level(logging.WARNING)

    app_module._index_rag_docs_safely(BrokenRag())

    assert "RAG background indexing failed" in caplog.text
    assert "embedding cache unavailable" in caplog.text


def test_runtime_constructs_the_canonical_rag_pipeline(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    monkeypatch.setattr(RAGPipeline, "document_count", lambda self: 1)

    rag = app_module._initialise_rag_runtime(tmp_path)

    assert type(rag) is RAGPipeline
    assert rag.config.persist_directory == str(tmp_path / "rag")


def test_runtime_constructs_when_chromadb_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.setitem(sys.modules, "chromadb", None)
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    monkeypatch.setattr(RAGPipeline, "document_count", lambda self: 1)

    rag = app_module._initialise_rag_runtime(tmp_path)

    assert type(rag) is RAGPipeline
    assert rag.config.persist_directory == str(tmp_path / "rag")


def test_runtime_closes_rag_when_indexer_cannot_start(monkeypatch, tmp_path) -> None:
    """A failed indexer start must close the already-opened pipeline, not leak it."""
    closed: list[object] = []

    class ExplodingThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.setenv("FLINTTRADE_RAG_AUTO_INDEX", "true")
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    monkeypatch.setattr(RAGPipeline, "document_count", lambda self: 0)
    monkeypatch.setattr(RAGPipeline, "close", lambda self: closed.append(self))
    monkeypatch.setattr(app_module.threading, "Thread", ExplodingThread)

    rag = app_module._initialise_rag_runtime(tmp_path)

    assert rag is None
    assert len(closed) == 1


def test_runtime_attaches_background_indexer_before_start(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.setenv("FLINTTRADE_RAG_AUTO_INDEX", "true")
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    monkeypatch.setattr(RAGPipeline, "document_count", lambda self: 0)
    attached: list[tuple[RAGPipeline, object]] = []
    started: list[object] = []

    class FakeThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            started.append(self)

    monkeypatch.setattr(app_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        RAGPipeline,
        "attach_indexer_thread",
        lambda self, thread: attached.append((self, thread)),
    )

    rag = app_module._initialise_rag_runtime(tmp_path)

    assert type(rag) is RAGPipeline
    assert len(attached) == 1
    assert attached[0][0] is rag
    assert started == [attached[0][1]]


def test_runtime_refuses_to_shadow_legacy_chroma_vectors(monkeypatch, tmp_path, caplog) -> None:
    """Startup must surface preserved legacy vectors instead of treating RAG as empty."""
    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.delenv("FLINTTRADE_RAG_AUTO_INDEX", raising=False)
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    legacy_db = rag_dir / "chroma.sqlite3"
    legacy_db.write_bytes(b"legacy-vector-data")
    caplog.set_level(logging.WARNING)

    rag = app_module._initialise_rag_runtime(tmp_path)

    assert rag is None
    assert "Legacy Chroma vector data detected" in caplog.text
    assert legacy_db.read_bytes() == b"legacy-vector-data"
    assert not (rag_dir / "flinttrade_vectors.sqlite").exists()


def test_runtime_retains_background_indexer_until_joined(monkeypatch, tmp_path) -> None:
    """Auto-index must keep the worker so shutdown can quiesce it before close."""
    started = threading.Event()
    release = threading.Event()

    def blocking_index(self, _path: str) -> int:
        started.set()
        assert release.wait(timeout=2.0)
        return 1

    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.setenv("FLINTTRADE_RAG_AUTO_INDEX", "true")
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    monkeypatch.setattr(RAGPipeline, "document_count", lambda self: 0)
    monkeypatch.setattr(RAGPipeline, "index_directory", blocking_index)

    rag = app_module._initialise_rag_runtime(tmp_path)
    indexer = getattr(rag, "_indexer_thread", None)

    try:
        assert type(rag) is RAGPipeline
        assert isinstance(indexer, threading.Thread)
        assert started.wait(timeout=2.0)
        assert indexer.is_alive()
    finally:
        release.set()
        if isinstance(indexer, threading.Thread):
            indexer.join(timeout=2.0)
        if rag is not None:
            rag.close()

    assert indexer is not None and not indexer.is_alive()


def test_join_rag_indexer_waits_for_the_retained_worker() -> None:
    """The shutdown helper must block until the daemon indexer finishes."""
    started = threading.Event()
    release = threading.Event()

    def hold() -> None:
        started.set()
        release.wait(timeout=2.0)

    indexer = threading.Thread(target=hold, name="rag-indexer", daemon=True)
    rag = SimpleNamespace(_indexer_thread=indexer)
    indexer.start()
    assert started.wait(timeout=1.0)

    joined = threading.Event()

    def join_worker() -> None:
        app_module._join_rag_indexer(rag)
        joined.set()

    waiter = threading.Thread(target=join_worker, name="rag-indexer-join", daemon=True)
    waiter.start()
    waiter.join(timeout=0.05)
    assert not joined.is_set()
    release.set()
    waiter.join(timeout=2.0)
    assert joined.is_set()
    assert not indexer.is_alive()
