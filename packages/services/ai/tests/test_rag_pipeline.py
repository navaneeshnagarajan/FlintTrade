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

from flinttrade_ai.rag_pipeline import (
    Document,
    DocumentLoader,
    DomainFilter,
    EmbeddingProvider,
    LegacyRetrievedChunk,
    LoadedDocument,
    PipelineConfig,
    RAGEngine,
    RAGPipeline,
    RAGResponse,
    RAGResult,
    RetrievedChunk,
    TextChunk,
    TextChunker,
    VectorStore,
    _content_hash,
    chunk_text,
    content_hash,
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

    def test_public_compatibility_helper_uses_canonical_hash(self) -> None:
        assert content_hash("hello") == _content_hash("hello")


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------


class TestTextChunker:
    def test_short_text_returns_single_chunk(self) -> None:
        chunker = TextChunker(chunk_size=512, overlap=64)
        result = chunker.chunk_text("Short text.")
        assert len(result) == 1
        assert result[0] == "Short text."

    def test_public_compatibility_helper_uses_production_defaults(self) -> None:
        assert chunk_text("Short text.") == ["Short text."]

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
    def test_canonical_and_legacy_document_defaults_remain_distinct(self) -> None:
        assert LoadedDocument(content="canonical").doc_type == "general"
        assert Document(content="legacy").doc_type == ""

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

    def test_load_file_python(self, tmp_path: Path) -> None:
        source = tmp_path / "strategy.py"
        source.write_text("def signal():\n    return 'BUY'\n")

        doc = DocumentLoader().load_file(source)

        assert doc is not None
        assert "def signal" in doc.content
        assert doc.doc_type == "strategy"

    def test_load_file_pdf_joins_extracted_pages(self, tmp_path: Path) -> None:
        pdf = tmp_path / "market_report.pdf"
        pdf.write_bytes(b"%PDF-mocked")
        fake_pypdf = MagicMock()
        fake_pypdf.PdfReader.return_value.pages = [
            MagicMock(extract_text=MagicMock(return_value="Page one")),
            MagicMock(extract_text=MagicMock(return_value="Page two")),
        ]

        with patch.dict("sys.modules", {"pypdf": fake_pypdf}):
            doc = DocumentLoader().load_file(pdf)

        assert doc is not None
        assert doc.content == "Page one\nPage two"
        assert doc.doc_type == "market_report"

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
        assert len(docs) == 3
        assert {Path(doc.source).suffix for doc in docs} == {".md", ".txt", ".py"}

    def test_load_directory_honours_caller_selected_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("markdown")
        (tmp_path / "b.py").write_text("python")

        docs = DocumentLoader().load_directory(tmp_path, extensions=(".py",))

        assert [Path(doc.source).suffix for doc in docs] == [".py"]

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

    def test_sentence_transformer_initialisation_error_becomes_fallback_signal(self) -> None:
        broken_module = MagicMock()
        broken_module.SentenceTransformer.side_effect = ValueError("model cache corrupt")
        provider = EmbeddingProvider(provider="sentence_transformers")

        with patch.dict("sys.modules", {"sentence_transformers": broken_module}):
            with pytest.raises(RuntimeError, match="sentence-transformers unavailable"):
                provider.embed(["hello"])


class TestDomainFilter:
    def test_semantic_backend_failure_falls_through_to_retrieval(self) -> None:
        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("embedding backend unavailable")
        domain_filter = DomainFilter(embedding_provider=provider)

        assert domain_filter.is_on_topic("How do I adjust the second leg?")

    def test_keyword_miss_without_semantic_backend_is_rejected(self) -> None:
        assert not DomainFilter().is_on_topic("How do I bake a sourdough loaf?")


# ---------------------------------------------------------------------------
# VectorStore (with mocked ChromaDB)
# ---------------------------------------------------------------------------


def _make_mock_collection(
    count: int = 0,
    *,
    space: str = "cosine",
    embedding_mode: str | None = "external",
) -> MagicMock:
    coll = MagicMock()
    coll.count.return_value = count
    coll.configuration = {"hnsw": {"space": space}}
    coll.metadata = {"hnsw:space": space}
    if embedding_mode is not None:
        coll.metadata["flinttrade_embedding_mode"] = embedding_mode

    def _modify(*, metadata) -> None:
        coll.metadata = metadata

    coll.modify.side_effect = _modify
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
        chunks = [TextChunk(content="hello", chunk_id="abc_0", source="test.md", doc_type="strategy")]
        count = store.upsert(chunks)
        assert count == 1
        coll.upsert.assert_called_once()
        assert coll.upsert.call_args.kwargs["embeddings"] == [[0.1] * 384]

    def test_upsert_falls_back_to_chroma_embeddings(self) -> None:
        coll = _make_mock_collection(embedding_mode=None)
        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("embedding backend unavailable")
        store = VectorStore(collection_name="test", embedding_provider=provider)
        store._collection = coll

        store.upsert([TextChunk(content="hello", chunk_id="abc_0")])

        assert "embeddings" not in coll.upsert.call_args.kwargs
        assert coll.upsert.call_args.kwargs["documents"] == ["hello"]

    def test_upsert_falls_back_for_non_runtime_provider_errors(self) -> None:
        coll = _make_mock_collection(embedding_mode=None)
        provider = MagicMock()
        provider.embed.side_effect = ValueError("invalid local model")
        store = VectorStore(collection_name="test", embedding_provider=provider)
        store._collection = coll

        store.upsert([TextChunk(content="hello", chunk_id="abc_0")])

        assert "embeddings" not in coll.upsert.call_args.kwargs

    def test_upsert_does_not_mask_collection_write_failures(self) -> None:
        coll = _make_mock_collection()
        coll.upsert.side_effect = RuntimeError("database is read-only")
        store = VectorStore(
            collection_name="test",
            embedding_provider=EmbeddingProvider(custom_fn=lambda _texts: [[0.1, 0.2]]),
        )
        store._collection = coll

        with pytest.raises(RuntimeError, match="database is read-only"):
            store.upsert([TextChunk(content="hello", chunk_id="abc_0")])

        assert coll.upsert.call_count == 1

    def test_fallback_index_then_query_uses_chroma_embedding_path(self) -> None:
        coll = _make_mock_collection(embedding_mode=None)
        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("embedding backend unavailable")
        store = VectorStore(collection_name="test", embedding_provider=provider)
        store._collection = coll

        store.upsert([TextChunk(content="NIFTY theta", chunk_id="abc_0", source="guide.md")])
        coll.count.return_value = 1
        results = store.search("second leg", similarity_threshold=0.0)

        assert results[0].content == "chunk content"
        assert "embeddings" not in coll.upsert.call_args.kwargs
        coll.query.assert_called_once_with(query_texts=["second leg"], n_results=1, where=None)

    def test_reopens_existing_persistent_collection_without_reindexing(self, tmp_path: Path) -> None:
        chromadb = pytest.importorskip("chromadb")
        persist_directory = str(tmp_path / "chroma")
        old_client = chromadb.PersistentClient(path=persist_directory)
        old_collection = old_client.get_or_create_collection(
            "flinttrade_docs",
            metadata={"hnsw:space": "cosine", "flinttrade_embedding_mode": "external"},
        )
        old_collection.upsert(
            ids=["legacy_0"],
            documents=["Theta measures time decay."],
            embeddings=[[1.0, 0.0]],
            metadatas=[{"source": "legacy.md", "doc_type": "strategy"}],
        )

        store = VectorStore(
            collection_name="flinttrade_docs",
            persist_directory=persist_directory,
            embedding_provider=EmbeddingProvider(custom_fn=lambda _texts: [[1.0, 0.0]]),
        )

        results = store.search("theta", top_k=1, similarity_threshold=0.0)

        assert store.count() == 1
        assert results[0].content == "Theta measures time decay."
        assert results[0].source == "legacy.md"

    def test_unmarked_populated_collection_fails_closed_without_relabelling(self, tmp_path: Path) -> None:
        chromadb = pytest.importorskip("chromadb")
        persist_directory = str(tmp_path / "chroma")
        client = chromadb.PersistentClient(path=persist_directory)
        collection = client.get_or_create_collection("legacy_docs")
        collection.upsert(
            ids=["legacy_0"],
            documents=["Unknown embedding space"],
            embeddings=[[1.0, 0.0]],
        )
        store = VectorStore(
            collection_name="legacy_docs",
            persist_directory=persist_directory,
            embedding_provider=EmbeddingProvider(custom_fn=lambda _texts: [[1.0, 0.0]]),
        )

        with pytest.raises(RuntimeError, match="embedding mode is unknown"):
            store.search("query")

        assert "flinttrade_embedding_mode" not in (store._get_collection().metadata or {})

    def test_fresh_persistent_collection_applies_cosine_threshold(self, tmp_path: Path) -> None:
        pytest.importorskip("chromadb")
        persist_directory = str(tmp_path / "chroma")

        def _embed(texts: list[str]) -> list[list[float]]:
            return [[0.8, 0.6] if text == "adjust the leg" else [1.0, 0.0] for text in texts]

        store = VectorStore(
            collection_name="flinttrade_docs",
            persist_directory=persist_directory,
            embedding_provider=EmbeddingProvider(custom_fn=_embed),
        )
        store.upsert([TextChunk(content="Theta adjustment guide", chunk_id="guide_0")])

        results = store.search("adjust the leg", top_k=1, similarity_threshold=0.7)

        assert results[0].score == pytest.approx(0.8)
        assert store._get_collection().configuration["hnsw"]["space"] == "cosine"

    def test_fresh_collection_uses_cosine_distance(self) -> None:
        coll = _make_mock_collection(count=0, embedding_mode=None)
        client = _make_mock_chroma_client(coll)
        store = VectorStore(collection_name="test")
        store._client = client

        assert store._get_collection() is coll
        client.get_or_create_collection.assert_called_once_with(
            name="test",
            metadata={
                "hnsw:space": "cosine",
                "flinttrade_distance_space": "cosine",
            },
        )

    def test_legacy_l2_distance_is_converted_to_cosine_similarity(self) -> None:
        coll = _make_mock_collection(count=1, space="l2", embedding_mode="external")
        coll.query.return_value["distances"] = [[0.4]]
        store = VectorStore(
            collection_name="test",
            embedding_provider=EmbeddingProvider(custom_fn=lambda _texts: [[0.8, 0.6]]),
        )
        store._collection = coll

        results = store.search("adjust the leg", similarity_threshold=0.7)

        assert results[0].score == pytest.approx(0.8)

    def test_external_embedding_mode_never_falls_back_to_chroma_on_query(self) -> None:
        coll = _make_mock_collection(count=1, embedding_mode="external")
        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("provider temporarily unavailable")
        store = VectorStore(collection_name="test", embedding_provider=provider)
        store._collection = coll

        with pytest.raises(RuntimeError, match="external embeddings"):
            store.search("theta")

        coll.query.assert_not_called()

    def test_external_embedding_mode_never_falls_back_to_chroma_on_upsert(self) -> None:
        coll = _make_mock_collection(count=1, embedding_mode="external")
        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("provider temporarily unavailable")
        store = VectorStore(collection_name="test", embedding_provider=provider)
        store._collection = coll

        with pytest.raises(RuntimeError, match="external embeddings"):
            store.upsert([TextChunk(content="theta", chunk_id="theta_0")])

        coll.upsert.assert_not_called()

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
        store._collection.query.assert_called_once_with(
            query_embeddings=[[0.1] * 384],
            n_results=3,
            where=None,
        )

    def test_search_filters_below_threshold(self) -> None:
        """Chunks with score < threshold are excluded."""
        store, _ = self._make_store()
        # distance=0.1 → score=0.9; threshold=0.95 should exclude it.
        results = store.search("query", similarity_threshold=0.95)
        assert results == []

    def test_search_clamps_similarity_to_unit_interval(self) -> None:
        store, coll = self._make_store()
        coll.query.return_value["distances"] = [[-0.25]]

        results = store.search("query")

        assert results[0].score == 1.0

    def test_count_returns_collection_count(self) -> None:
        store, _ = self._make_store()
        assert store.count() == 5

    def test_delete_collection_clears_cached_collection(self) -> None:
        store, _ = self._make_store()

        store.delete_collection()

        store._client.delete_collection.assert_called_once_with("test")
        assert store._collection is None


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

    def test_index_document_accepts_document_with_arbitrary_metadata(self) -> None:
        pipeline = self._make_pipeline()
        pipeline._store.upsert = MagicMock(return_value=1)
        doc = Document(
            content="NIFTY options",
            source="guide.md",
            doc_type="strategy",
            metadata={"desk": "derivatives"},
        )

        assert pipeline.index_document(doc) == 1

        chunks = pipeline._store.upsert.call_args.args[0]
        assert chunks[0].metadata == {"desk": "derivatives"}

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
        pipeline._store.search = MagicMock(return_value=[RetrievedChunk(content="relevant chunk", score=0.9)])
        results = pipeline.retrieve("test query", top_k=3)
        assert len(results) == 1
        assert results[0].content == "relevant chunk"
        pipeline._store.search.assert_called_once_with(
            "test query", top_k=3, doc_type=None, similarity_threshold=pytest.approx(0.7)
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
        pipeline._store.search = MagicMock(return_value=[RetrievedChunk(content="NIFTY max pain is 22000", score=0.95)])
        # Patch the LLMMessage import inside rag_pipeline.query to avoid
        # the circular dependency on llm_client in the test environment.
        mock_msg_cls = MagicMock(return_value=MagicMock())
        with patch.dict(
            "sys.modules",
            {"flinttrade_ai.llm_client": MagicMock(LLMMessage=mock_msg_cls)},
        ):
            result = pipeline.query("Where is max pain?")
        assert result.query == "Where is max pain?"

    def test_query_can_disable_the_configured_domain_filter_per_call(self) -> None:
        domain_filter = MagicMock()
        domain_filter.is_on_topic.return_value = False
        pipeline = self._make_pipeline(with_llm=True)
        pipeline._domain_filter = domain_filter
        pipeline._store.search = MagicMock(return_value=[])

        result = pipeline.query("Tell me anything", enable_domain_filter=False)

        assert result.error == "No relevant documents found"
        domain_filter.is_on_topic.assert_not_called()

    def test_default_prompt_preserves_strict_context_only_contract(self) -> None:
        pipeline = self._make_pipeline(with_llm=True)
        pipeline._store.search = MagicMock(return_value=[RetrievedChunk(content="NIFTY max pain is 22000", score=0.95)])

        pipeline.query("Where is max pain?")

        messages = pipeline._llm.chat.call_args.args[0]
        assert "provided context" in messages[0].content
        assert "doesn't contain the answer" in messages[0].content
        assert "concise and specific" in messages[0].content

    def test_document_count_delegates_to_store(self) -> None:
        pipeline = self._make_pipeline()
        pipeline._store.count = MagicMock(return_value=42)
        assert pipeline.document_count() == 42

    def test_delete_collection_delegates_to_store(self) -> None:
        pipeline = self._make_pipeline()
        pipeline._store.delete_collection = MagicMock()

        pipeline.delete_collection()

        pipeline._store.delete_collection.assert_called_once_with()

    def test_pipeline_config_defaults(self) -> None:
        cfg = PipelineConfig()
        assert cfg.chunk_size == 1000
        assert cfg.chunk_overlap == 200
        assert cfg.embedding_provider == "sentence_transformers"
        assert cfg.top_k == 5
        assert cfg.similarity_threshold == pytest.approx(0.7)
        assert cfg.collection_name == "flinttrade_docs"


class TestLegacyRAGCompatibility:
    """The canonical module keeps the former public API without duplicate logic."""

    def test_legacy_document_and_response_models_remain_available(self) -> None:
        doc = Document(content="NIFTY options", source="guide.md", doc_type="strategy")
        response = RAGResponse(answer="answer", query="question")

        assert isinstance(doc, LoadedDocument)
        assert response.success

    def test_canonical_result_positional_order_is_preserved(self) -> None:
        chunk = RetrievedChunk(content="context")

        result = RAGResult("answer", "question", [chunk], "")

        assert result.answer == "answer"
        assert result.query == "question"
        assert result.chunks_used == [chunk]

    def test_canonical_retrieved_chunk_default_remains_general(self) -> None:
        assert RetrievedChunk(content="context").doc_type == "general"

    def test_legacy_module_is_a_reexport_shim(self) -> None:
        from flinttrade_ai.rag import RAGEngine as LegacyRAGEngine

        assert LegacyRAGEngine is RAGEngine

    def test_response_positional_field_order_matches_the_legacy_contract(self) -> None:
        chunk = LegacyRetrievedChunk(content="context")

        response = RAGResponse("answer", [chunk], "question", "")

        assert response.answer == "answer"
        assert response.chunks_used == [chunk]
        assert response.query == "question"

    def test_retrieved_chunk_legacy_default_is_empty_doc_type(self) -> None:
        assert LegacyRetrievedChunk(content="context").doc_type == ""

    def test_legacy_module_exports_the_legacy_chunk_type(self) -> None:
        from flinttrade_ai.rag import RetrievedChunk as LegacyExport

        assert LegacyExport is LegacyRetrievedChunk

    def test_engine_constructor_maps_legacy_options_to_pipeline_config(self) -> None:
        engine = RAGEngine(
            collection_name="legacy_docs",
            persist_directory="/tmp/flinttrade-rag-test",
            embedding_model="legacy-model",
        )

        assert isinstance(engine, RAGPipeline)
        assert engine.config.collection_name == "legacy_docs"
        assert engine.config.persist_directory == "/tmp/flinttrade-rag-test"
        assert engine.config.embedding_model == "legacy-model"
        assert engine._domain_filter is None

    def test_engine_can_enable_the_canonical_domain_filter(self) -> None:
        domain_filter = MagicMock()

        engine = RAGEngine(domain_filter=domain_filter, enable_domain_filter=True)

        assert engine._domain_filter is domain_filter

    def test_engine_can_enable_a_domain_filter_per_query(self) -> None:
        domain_filter = MagicMock()
        domain_filter.is_on_topic.return_value = False
        engine = RAGEngine(llm_client=MagicMock())

        result = engine.query(
            "Tell me a bedtime story",
            domain_filter=domain_filter,
            enable_domain_filter=True,
        )

        assert result.answer == DomainFilter.REFUSAL_MESSAGE
        domain_filter.is_on_topic.assert_called_once_with("Tell me a bedtime story")

    def test_engine_retains_a_disabled_custom_filter_for_per_query_enable(self) -> None:
        domain_filter = MagicMock()
        domain_filter.is_on_topic.return_value = False
        engine = RAGEngine(
            llm_client=MagicMock(),
            domain_filter=domain_filter,
            enable_domain_filter=False,
        )

        result = engine.query("Tell me a bedtime story", enable_domain_filter=True)

        assert result.answer == DomainFilter.REFUSAL_MESSAGE
        domain_filter.is_on_topic.assert_called_once_with("Tell me a bedtime story")

    def test_engine_exposes_legacy_collection_accessor_without_second_store(self) -> None:
        engine = RAGEngine()
        engine._store._get_collection = MagicMock(return_value="collection")

        assert engine._get_collection() == "collection"
        engine._store._get_collection.assert_called_once_with()

    def test_engine_retrieve_maps_n_results_to_top_k(self) -> None:
        engine = RAGEngine()
        engine._store.search = MagicMock(return_value=[])

        engine.retrieve("NIFTY", n_results=3, similarity_threshold=0.8)

        engine._store.search.assert_called_once_with(
            "NIFTY",
            top_k=3,
            doc_type=None,
            similarity_threshold=0.8,
        )

    def test_engine_directory_extensions_keep_legacy_selection(self, tmp_path: Path) -> None:
        (tmp_path / "included.py").write_text("print('indexed')")
        (tmp_path / "excluded.md").write_text("not selected")
        engine = RAGEngine()
        engine._store.upsert = MagicMock(side_effect=lambda chunks: len(chunks))

        count = engine.index_directory(str(tmp_path), extensions=(".py",))

        assert count == 1
        assert engine._store.upsert.call_args.args[0][0].source.endswith("included.py")

    def test_engine_preserves_arbitrary_text_extension_indexing(self, tmp_path: Path) -> None:
        source = tmp_path / "guide.rst"
        source.write_text("Theta adjustment guide")
        engine = RAGEngine()
        engine._store.upsert = MagicMock(side_effect=lambda chunks: len(chunks))

        assert engine.index_file(str(source)) == 1
        assert engine.index_directory(str(tmp_path), extensions=(".rst",)) == 1
        assert engine._store.upsert.call_count == 2

    def test_engine_directory_defaults_include_pdf(self, tmp_path: Path) -> None:
        pdf = tmp_path / "guide.pdf"
        pdf.write_bytes(b"%PDF-mocked")
        fake_pypdf = MagicMock()
        fake_pypdf.PdfReader.return_value.pages = [MagicMock(extract_text=MagicMock(return_value="Theta guide"))]
        engine = RAGEngine()
        engine._store.upsert = MagicMock(side_effect=lambda chunks: len(chunks))

        with patch.dict("sys.modules", {"pypdf": fake_pypdf}):
            count = engine.index_directory(str(tmp_path))

        assert count == 1
        assert engine._store.upsert.call_args.args[0][0].source.endswith("guide.pdf")

    def test_engine_query_accepts_canonical_top_k_alias(self) -> None:
        engine = RAGEngine(llm_client=MagicMock())
        engine._store.search = MagicMock(return_value=[])

        engine.query("What is theta?", top_k=3)

        engine._store.search.assert_called_once_with(
            "What is theta?",
            top_k=3,
            doc_type=None,
            similarity_threshold=pytest.approx(0.7),
        )
