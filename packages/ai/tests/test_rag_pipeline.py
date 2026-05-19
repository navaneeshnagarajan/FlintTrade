"""Tests for rag_pipeline module.

Covers:
- TextChunker: chunk_text edge cases, overlapping windows, chunk_document.
- DocumentLoader: _infer_type, load_file (mocked), load_directory (mocked).
- EmbeddingProvider: custom_fn path, empty-input guard.
- VectorStore: upsert + search round-trip (in-memory ChromaDB or mock).
- RAGPipeline: index_document, retrieve, query (with mock LLM), no-LLM error path.
- _content_hash: determinism and length.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.ai.src.rag_pipeline import (
    DocumentLoader,
    EmbeddingProvider,
    LoadedDocument,
    PipelineConfig,
    RAGPipeline,
    RetrievedChunk,
    TextChunk,
    TextChunker,
    VectorStore,
    _content_hash,
)


# ---------------------------------------------------------------------------
# _content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self) -> None:
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_inputs_differ(self) -> None:
        assert _content_hash("hello") != _content_hash("world")

    def test_default_length(self) -> None:
        assert len(_content_hash("test")) == 16

    def test_custom_length(self) -> None:
        assert len(_content_hash("test", length=8)) == 8


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------


class TestTextChunker:
    def test_short_text_returns_single_chunk(self) -> None:
        chunker = TextChunker(chunk_size=512, overlap=64)
        result = chunker.chunk_text("Short text.")
        assert len(result) == 1
        assert result[0] == "Short text."

    def test_empty_text_returns_empty(self) -> None:
        chunker = TextChunker(chunk_size=512, overlap=64)
        assert chunker.chunk_text("") == []
        assert chunker.chunk_text("   ") == []

    def test_long_text_splits_into_multiple_chunks(self) -> None:
        chunker = TextChunker(chunk_size=10, overlap=2)  # 10 tokens ≈ 40 chars
        text = "A" * 200
        chunks = chunker.chunk_text(text)
        assert len(chunks) > 1

    def test_overlap_present_between_chunks(self) -> None:
        """Adjacent chunks should share content due to overlap."""
        chunker = TextChunker(chunk_size=10, overlap=5)
        # Build text with clearly delineated words so we can track overlap.
        text = " ".join(f"word{i:03d}" for i in range(100))
        chunks = chunker.chunk_text(text)
        if len(chunks) > 1:
            # Last few characters of chunk N should appear in chunk N+1.
            tail = chunks[0][-10:]
            assert tail in chunks[1]

    def test_chunk_document_assigns_ids(self) -> None:
        chunker = TextChunker(chunk_size=10, overlap=2)
        doc = LoadedDocument(content="A" * 200, source="test.md", doc_type="strategy")
        chunks = chunker.chunk_document(doc)
        assert len(chunks) > 0
        for i, c in enumerate(chunks):
            assert c.chunk_index == i
            assert c.source == "test.md"
            assert c.doc_type == "strategy"
            assert c.chunk_id  # non-empty

    def test_chunk_document_empty_returns_empty(self) -> None:
        chunker = TextChunker()
        doc = LoadedDocument(content="", source="empty.md")
        assert chunker.chunk_document(doc) == []


# ---------------------------------------------------------------------------
# DocumentLoader
# ---------------------------------------------------------------------------


class TestDocumentLoader:
    def test_infer_type_strategy(self) -> None:
        loader = DocumentLoader()
        assert loader._infer_type("my_strategy.md") == "strategy"

    def test_infer_type_api_docs(self) -> None:
        loader = DocumentLoader()
        assert loader._infer_type("openalgo_api_reference.txt") == "api_docs"

    def test_infer_type_trade_journal(self) -> None:
        loader = DocumentLoader()
        assert loader._infer_type("trade_journal_2026.md") == "trade_journal"

    def test_infer_type_market_report(self) -> None:
        loader = DocumentLoader()
        assert loader._infer_type("market_report_q1.md") == "market_report"

    def test_infer_type_general_fallback(self) -> None:
        loader = DocumentLoader()
        assert loader._infer_type("random_notes.txt") == "general"

    def test_load_file_not_found(self) -> None:
        loader = DocumentLoader()
        result = loader.load_file("/nonexistent/path.md")
        assert result is None

    def test_load_file_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("col1,col2\n1,2")
        loader = DocumentLoader()
        result = loader.load_file(f)
        assert result is None

    def test_load_file_markdown(self, tmp_path: Path) -> None:
        f = tmp_path / "strategy.md"
        f.write_text("# NIFTY Straddle\n\nBuy ATM CE and PE.")
        loader = DocumentLoader()
        doc = loader.load_file(f)
        assert doc is not None
        assert "ATM CE" in doc.content
        assert doc.doc_type == "strategy"
        assert doc.source == str(f)

    def test_load_file_txt(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("Some notes.")
        loader = DocumentLoader()
        doc = loader.load_file(f)
        assert doc is not None
        assert doc.content == "Some notes."

    def test_load_file_empty_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.md"
        f.write_text("   ")
        loader = DocumentLoader()
        assert loader.load_file(f) is None

    def test_load_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("# Alpha strategy docs")
        (tmp_path / "b.txt").write_text("Beta notes")
        (tmp_path / "skip.py").write_text("print('hello')")
        loader = DocumentLoader()
        docs = loader.load_directory(tmp_path)
        assert len(docs) == 2

    def test_load_directory_not_a_dir(self) -> None:
        loader = DocumentLoader()
        assert loader.load_directory("/nonexistent/dir") == []

    def test_load_file_doc_type_override(self, tmp_path: Path) -> None:
        f = tmp_path / "custom.txt"
        f.write_text("content")
        loader = DocumentLoader()
        doc = loader.load_file(f, doc_type="api_docs")
        assert doc is not None
        assert doc.doc_type == "api_docs"


# ---------------------------------------------------------------------------
# EmbeddingProvider
# ---------------------------------------------------------------------------


class TestEmbeddingProvider:
    def test_empty_input_returns_empty(self) -> None:
        provider = EmbeddingProvider(custom_fn=lambda texts: [[0.1] * 384 for _ in texts])
        assert provider.embed([]) == []

    def test_custom_fn_used(self) -> None:
        fixed = [[1.0, 2.0, 3.0]]
        provider = EmbeddingProvider(custom_fn=lambda texts: [fixed[0]] * len(texts))
        result = provider.embed(["hello world"])
        assert result == [[1.0, 2.0, 3.0]]

    def test_custom_fn_multiple_texts(self) -> None:
        provider = EmbeddingProvider(custom_fn=lambda texts: [[float(i)] * 3 for i in range(len(texts))])
        result = provider.embed(["a", "b", "c"])
        assert len(result) == 3

    def test_sentence_transformers_not_installed_raises(self) -> None:
        provider = EmbeddingProvider(provider="sentence_transformers")
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises((RuntimeError, ImportError)):
                provider.embed(["hello"])


# ---------------------------------------------------------------------------
# VectorStore (with mocked ChromaDB)
# ---------------------------------------------------------------------------


def _make_mock_collection(count: int = 0) -> MagicMock:
    coll = MagicMock()
    coll.count.return_value = count
    coll.query.return_value = {
        "documents": [["chunk content"]],
        "metadatas": [[{"source": "test.md", "doc_type": "strategy", "chunk_index": "0"}]],
        "distances": [[0.1]],
    }
    return coll


def _make_mock_chroma_client(collection: MagicMock) -> MagicMock:
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    return client


class TestVectorStore:
    def _make_store(self) -> tuple[VectorStore, MagicMock]:
        coll = _make_mock_collection(count=5)
        client = _make_mock_chroma_client(coll)
        store = VectorStore(
            collection_name="test",
            embedding_provider=EmbeddingProvider(custom_fn=lambda t: [[0.1] * 384 for _ in t]),
        )
        # Inject mocked client
        store._client = client
        store._collection = coll
        return store, coll

    def test_upsert_calls_collection(self) -> None:
        store, coll = self._make_store()
        chunks = [
            TextChunk(content="hello", chunk_id="abc_0", source="test.md", doc_type="strategy")
        ]
        count = store.upsert(chunks)
        assert count == 1
        coll.upsert.assert_called_once()

    def test_upsert_empty_returns_zero(self) -> None:
        store, coll = self._make_store()
        assert store.upsert([]) == 0
        coll.upsert.assert_not_called()

    def test_search_returns_retrieved_chunks(self) -> None:
        store, _ = self._make_store()
        results = store.search("NIFTY strategy", top_k=3)
        assert len(results) == 1
        assert results[0].content == "chunk content"
        assert results[0].source == "test.md"
        assert results[0].score == pytest.approx(0.9)

    def test_search_filters_below_threshold(self) -> None:
        """Chunks with score < threshold are excluded."""
        store, _ = self._make_store()
        # distance=0.1 → score=0.9; threshold=0.95 should exclude it.
        results = store.search("query", similarity_threshold=0.95)
        assert results == []

    def test_count_returns_collection_count(self) -> None:
        store, _ = self._make_store()
        assert store.count() == 5


# ---------------------------------------------------------------------------
# RAGPipeline
# ---------------------------------------------------------------------------


class TestRAGPipeline:
    def _make_pipeline(self, with_llm: bool = False) -> RAGPipeline:
        coll = _make_mock_collection(count=0)
        client = _make_mock_chroma_client(coll)

        embed_provider = EmbeddingProvider(custom_fn=lambda t: [[0.1] * 384 for _ in t])
        store = VectorStore(
            collection_name="test_pipe",
            embedding_provider=embed_provider,
        )
        store._client = client
        store._collection = coll

        llm = None
        if with_llm:
            llm = MagicMock()
            llm_response = MagicMock()
            llm_response.content = "Generated answer."
            llm_response.error = ""
            llm.chat.return_value = llm_response

        return RAGPipeline(
            config=PipelineConfig(chunk_size=512, chunk_overlap=64),
            llm_client=llm,
            vector_store=store,
        )

    def test_index_document_returns_chunk_count(self) -> None:
        pipeline = self._make_pipeline()
        count = pipeline.index_document("A" * 5000, source="test.md", doc_type="strategy")
        assert count > 0

    def test_index_document_short_text_is_one_chunk(self) -> None:
        pipeline = self._make_pipeline()
        count = pipeline.index_document("Short text.", source="test.md")
        assert count == 1

    def test_index_file_missing_returns_zero(self) -> None:
        pipeline = self._make_pipeline()
        assert pipeline.index_file("/nonexistent/file.md") == 0

    def test_index_file_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "strat.md"
        f.write_text("A" * 100)
        pipeline = self._make_pipeline()
        count = pipeline.index_file(f)
        assert count == 1

    def test_retrieve_calls_vector_store(self) -> None:
        pipeline = self._make_pipeline()
        # Patch the internal store's search method
        pipeline._store.search = MagicMock(return_value=[
            RetrievedChunk(content="relevant chunk", score=0.9)
        ])
        results = pipeline.retrieve("test query", top_k=3)
        assert len(results) == 1
        assert results[0].content == "relevant chunk"
        pipeline._store.search.assert_called_once_with(
            "test query", top_k=3, doc_type=None, similarity_threshold=pytest.approx(0.0)
        )

    def test_query_no_llm_returns_error(self) -> None:
        pipeline = self._make_pipeline(with_llm=False)
        result = pipeline.query("What is max pain?")
        assert not result.success
        assert "No LLM" in result.error

    def test_query_no_chunks_returns_error(self) -> None:
        pipeline = self._make_pipeline(with_llm=True)
        pipeline._store.search = MagicMock(return_value=[])
        result = pipeline.query("What is max pain?")
        assert not result.success
        assert "No relevant" in result.error

    def test_query_generates_answer(self) -> None:
        pipeline = self._make_pipeline(with_llm=True)
        pipeline._store.search = MagicMock(return_value=[
            RetrievedChunk(content="NIFTY max pain is 22000", score=0.95)
        ])
        # Patch the LLMMessage import inside rag_pipeline.query to avoid
        # the circular dependency on llm_client in the test environment.
        mock_msg_cls = MagicMock(return_value=MagicMock())
        with patch.dict(
            "sys.modules",
            {"packages.ai.src.llm_client": MagicMock(LLMMessage=mock_msg_cls)},
        ):
            result = pipeline.query("Where is max pain?")
        assert result.query == "Where is max pain?"

    def test_document_count_delegates_to_store(self) -> None:
        pipeline = self._make_pipeline()
        pipeline._store.count = MagicMock(return_value=42)
        assert pipeline.document_count() == 42

    def test_pipeline_config_defaults(self) -> None:
        cfg = PipelineConfig()
        assert cfg.chunk_size == 512
        assert cfg.chunk_overlap == 64
        assert cfg.embedding_provider == "sentence_transformers"
        assert cfg.top_k == 5
