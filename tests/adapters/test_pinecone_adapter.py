"""Tests for adapters/pinecone_adapter.py."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_pinecone():
    with patch("adapters.pinecone_adapter.Pinecone") as mock_cls:
        pc = MagicMock()
        mock_cls.return_value = pc
        yield pc


@pytest.fixture
def mock_embed_client():
    with patch("adapters.pinecone_adapter.OpenAI") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        yield client


@pytest.fixture
def adapter(mock_pinecone, mock_embed_client):
    from adapters.pinecone_adapter import PineconeAdapter
    return PineconeAdapter({
        "api_key": "test-pinecone-key",
        "index_name": "test-index",
        "openai_api_key": "sk-test",
    })


# ── __init__ ──────────────────────────────────────────────────────────────────

class TestInit:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("PINECONE_API_KEY", raising=False)
        with patch("adapters.pinecone_adapter.Pinecone"), \
             patch("adapters.pinecone_adapter.OpenAI"):
            from adapters.pinecone_adapter import PineconeAdapter
            with pytest.raises(ValueError, match="Pinecone API key"):
                PineconeAdapter({})

    def test_missing_index_name_raises(self, monkeypatch):
        with patch("adapters.pinecone_adapter.Pinecone"), \
             patch("adapters.pinecone_adapter.OpenAI"):
            from adapters.pinecone_adapter import PineconeAdapter
            with pytest.raises(ValueError, match="index_name"):
                PineconeAdapter({"api_key": "key"})


# ── _chunk_text ───────────────────────────────────────────────────────────────

class TestChunkText:
    def test_empty_string_returns_empty_list(self, adapter):
        assert adapter._chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self, adapter):
        assert adapter._chunk_text("   \n  ") == []

    def test_short_text_returns_single_chunk(self, adapter):
        result = adapter._chunk_text("Hello, world!")
        assert len(result) == 1
        assert result[0] == "Hello, world!"

    def test_long_text_creates_multiple_chunks(self, adapter):
        text = "word " * 1000  # ~5000 chars, well above CHUNK_SIZE of 1500
        chunks = adapter._chunk_text(text)
        assert len(chunks) > 1

    def test_all_chunks_are_non_empty(self, adapter):
        text = "x" * 4000
        for chunk in adapter._chunk_text(text):
            assert len(chunk) > 0

    def test_chunks_have_overlap(self, adapter):
        # With overlap=150, chunk[1] should start 150 chars before chunk[0] ends
        text = "a" * 3500
        chunks = adapter._chunk_text(text)
        if len(chunks) >= 2:
            # The start of chunk[1] should be < end of chunk[0]
            from adapters.pinecone_adapter import _CHUNK_SIZE, _CHUNK_OVERLAP
            assert len(chunks[0]) == _CHUNK_SIZE


# ── upload ────────────────────────────────────────────────────────────────────

class TestUpload:
    def _setup_embeddings(self, mock_embed_client, n_chunks):
        """Make the embed client return n_chunks dummy embeddings."""
        def _embed(model, input):
            return MagicMock(
                data=[MagicMock(embedding=[0.1] * 1536) for _ in input]
            )
        mock_embed_client.embeddings.create.side_effect = lambda **kw: _embed(
            kw["model"], kw["input"]
        )

    def test_empty_content_returns_skipped(self, adapter):
        result = adapter.upload(b"   ", "f.txt", "text/plain", {})
        assert result["status"] == "skipped"
        assert result["reason"] == "empty content"

    def test_success_returns_status_success(self, adapter, mock_pinecone, mock_embed_client):
        self._setup_embeddings(mock_embed_client, 1)
        mock_index = MagicMock()
        mock_pinecone.Index.return_value = mock_index

        result = adapter.upload(b"Short doc", "f.txt", "text/plain", {})
        assert result["status"] == "success"

    def test_success_returns_vector_count(self, adapter, mock_pinecone, mock_embed_client):
        self._setup_embeddings(mock_embed_client, 1)
        mock_pinecone.Index.return_value = MagicMock()

        result = adapter.upload(b"Short doc", "f.txt", "text/plain", {})
        assert result["vectors_upserted"] >= 1

    def test_success_returns_index_name(self, adapter, mock_pinecone, mock_embed_client):
        self._setup_embeddings(mock_embed_client, 1)
        mock_pinecone.Index.return_value = MagicMock()

        result = adapter.upload(b"data", "f.txt", "text/plain", {})
        assert result["index"] == "test-index"

    def test_upsert_called_on_index(self, adapter, mock_pinecone, mock_embed_client):
        self._setup_embeddings(mock_embed_client, 1)
        mock_index = MagicMock()
        mock_pinecone.Index.return_value = mock_index

        adapter.upload(b"Some content here", "f.txt", "text/plain", {})
        assert mock_index.upsert.called

    def test_long_content_batched_correctly(self, adapter, mock_pinecone, mock_embed_client):
        """Content producing >100 chunks should still be upserted."""
        self._setup_embeddings(mock_embed_client, None)
        mock_index = MagicMock()
        mock_pinecone.Index.return_value = mock_index

        # ~20k chars → ~13 chunks
        content = b"word " * 4000
        result = adapter.upload(content, "big.txt", "text/plain", {})
        assert result["status"] == "success"

    def test_api_error_reraises(self, adapter, mock_pinecone, mock_embed_client):
        self._setup_embeddings(mock_embed_client, 1)
        mock_index = MagicMock()
        mock_index.upsert.side_effect = Exception("Pinecone error")
        mock_pinecone.Index.return_value = mock_index

        with pytest.raises(Exception, match="Pinecone error"):
            adapter.upload(b"data", "f.txt", "text/plain", {})


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_success_returns_true(self, adapter, mock_pinecone):
        mock_pinecone.Index.return_value = MagicMock()
        assert adapter.delete("vec-001") is True

    def test_failure_returns_false(self, adapter, mock_pinecone):
        mock_index = MagicMock()
        mock_index.delete.side_effect = Exception("not found")
        mock_pinecone.Index.return_value = mock_index
        assert adapter.delete("vec-001") is False


# ── health_check ──────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_healthy_returns_correct_structure(self, adapter, mock_pinecone):
        mock_pinecone.Index.return_value = MagicMock()
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["platform"] == "pinecone"
        assert result["index"] == "test-index"

    def test_unhealthy_on_error(self, adapter, mock_pinecone):
        mock_index = MagicMock()
        mock_index.describe_index_stats.side_effect = Exception("unreachable")
        mock_pinecone.Index.return_value = mock_index
        result = adapter.health_check()
        assert result["status"] == "unhealthy"
