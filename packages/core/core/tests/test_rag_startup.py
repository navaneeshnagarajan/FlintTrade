"""RAG startup controls."""

from __future__ import annotations

import logging
import sys
from types import ModuleType, SimpleNamespace

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
    monkeypatch.setitem(sys.modules, "chromadb", ModuleType("chromadb"))
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(provider="")))
    monkeypatch.setattr(RAGPipeline, "document_count", lambda self: 1)

    rag = app_module._initialise_rag_runtime(tmp_path)

    assert type(rag) is RAGPipeline
    assert rag.config.persist_directory == str(tmp_path / "rag")


def test_runtime_fails_closed_when_chromadb_is_missing(monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setenv("FLINTTRADE_RAG_ENABLED", "true")
    monkeypatch.setitem(sys.modules, "chromadb", None)
    caplog.set_level(logging.WARNING)

    assert app_module._initialise_rag_runtime(tmp_path) is None
    assert "RAG initialisation failed" in caplog.text
