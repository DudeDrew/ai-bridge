"""Tests for adapters/openai_adapter.py."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_openai_client():
    """Patch the OpenAI constructor and return the mock client instance."""
    with patch("adapters.openai_adapter.OpenAI") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        yield client


@pytest.fixture
def adapter(mock_openai_client):
    """OpenAIAdapter with a mocked client and no DB calls."""
    with patch("adapters.openai_adapter.DBManager"):
        from adapters.openai_adapter import OpenAIAdapter
        return OpenAIAdapter({"api_key": "sk-test", "vector_store_id": "vs_test"})


# ── upload ────────────────────────────────────────────────────────────────────

class TestUpload:
    def test_success_returns_status_success(self, adapter, mock_openai_client):
        mock_openai_client.files.create.return_value = MagicMock(id="file-abc")
        mock_openai_client.beta.vector_stores.files.create.return_value = MagicMock(id="vf-xyz")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            result = adapter.upload(b"hello world", "test.txt", "text/plain", {})

        assert result["status"] == "success"

    def test_success_returns_file_id(self, adapter, mock_openai_client):
        mock_openai_client.files.create.return_value = MagicMock(id="file-abc")
        mock_openai_client.beta.vector_stores.files.create.return_value = MagicMock(id="vf-xyz")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            result = adapter.upload(b"data", "f.txt", "text/plain", {})

        assert result["file_id"] == "file-abc"

    def test_success_returns_vector_store_id(self, adapter, mock_openai_client):
        mock_openai_client.files.create.return_value = MagicMock(id="file-abc")
        mock_openai_client.beta.vector_stores.files.create.return_value = MagicMock(id="vf-xyz")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            result = adapter.upload(b"data", "f.txt", "text/plain", {})

        assert result["vector_store_id"] == "vs_test"

    def test_duplicate_returns_skipped_status(self, adapter):
        with patch.object(adapter, "_check_dedup", return_value="file-existing"):
            result = adapter.upload(b"hello", "test.txt", "text/plain", {})

        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate"

    def test_duplicate_returns_cached_file_id(self, adapter):
        with patch.object(adapter, "_check_dedup", return_value="file-existing"):
            result = adapter.upload(b"hello", "test.txt", "text/plain", {})

        assert result["file_id"] == "file-existing"

    def test_api_failure_reraises_exception(self, adapter, mock_openai_client):
        mock_openai_client.files.create.side_effect = Exception("API error")

        with patch.object(adapter, "_check_dedup", return_value=None):
            with pytest.raises(Exception, match="API error"):
                adapter.upload(b"data", "f.txt", "text/plain", {})

    def test_dedup_key_stored_on_success(self, adapter, mock_openai_client):
        mock_openai_client.files.create.return_value = MagicMock(id="file-new")
        mock_openai_client.beta.vector_stores.files.create.return_value = MagicMock(id="vf-new")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup") as mock_store:
            adapter.upload(b"new content", "doc.txt", "text/plain", {})
            mock_store.assert_called_once()

    def test_files_create_called_with_correct_purpose(self, adapter, mock_openai_client):
        mock_openai_client.files.create.return_value = MagicMock(id="f1")
        mock_openai_client.beta.vector_stores.files.create.return_value = MagicMock(id="vf1")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            adapter.upload(b"data", "f.txt", "text/plain", {})

        call_kwargs = mock_openai_client.files.create.call_args.kwargs
        assert call_kwargs.get("purpose") == "assistants"


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_success_returns_true(self, adapter, mock_openai_client):
        assert adapter.delete("file-abc") is True

    def test_api_error_returns_false(self, adapter, mock_openai_client):
        mock_openai_client.beta.vector_stores.files.delete.side_effect = Exception("Not found")
        assert adapter.delete("file-abc") is False

    def test_delete_called_with_correct_ids(self, adapter, mock_openai_client):
        adapter.delete("file-xyz")
        mock_openai_client.beta.vector_stores.files.delete.assert_called_once_with(
            vector_store_id="vs_test", file_id="file-xyz"
        )


# ── health_check ──────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_healthy_when_api_reachable(self, adapter, mock_openai_client):
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["platform"] == "openai"

    def test_unhealthy_when_api_fails(self, adapter, mock_openai_client):
        mock_openai_client.models.list.side_effect = Exception("connection refused")
        result = adapter.health_check()
        assert result["status"] == "unhealthy"
        assert "error" in result

    def test_unhealthy_includes_error_message(self, adapter, mock_openai_client):
        mock_openai_client.models.list.side_effect = Exception("timeout")
        result = adapter.health_check()
        assert "timeout" in result["error"]


# ── list_resources ────────────────────────────────────────────────────────────

class TestListResources:
    def test_returns_list_of_file_dicts(self, adapter, mock_openai_client):
        mock_file = MagicMock(id="f1", status="processed")
        mock_openai_client.beta.vector_stores.files.list.return_value = MagicMock(
            data=[mock_file]
        )
        result = adapter.list_resources()
        assert isinstance(result, list)
        assert result[0]["id"] == "f1"

    def test_empty_store_returns_empty_list(self, adapter, mock_openai_client):
        mock_openai_client.beta.vector_stores.files.list.return_value = MagicMock(data=[])
        assert adapter.list_resources() == []
