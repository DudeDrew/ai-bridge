"""Tests for adapters/anthropic_adapter.py."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_anthropic_client():
    with patch("adapters.anthropic_adapter.anthropic.Anthropic") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        yield client


@pytest.fixture
def adapter(mock_anthropic_client):
    """AnthropicAdapter with a mocked client. DBManager is lazy-imported inside methods."""
    from adapters.anthropic_adapter import AnthropicAdapter
    return AnthropicAdapter({"api_key": "sk-ant-test"})


# ── __init__ ──────────────────────────────────────────────────────────────────

class TestInit:
    def test_missing_api_key_raises_value_error(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with patch("adapters.anthropic_adapter.anthropic.Anthropic"):
            from adapters.anthropic_adapter import AnthropicAdapter
            with pytest.raises(ValueError, match="API key"):
                AnthropicAdapter({})


# ── upload ────────────────────────────────────────────────────────────────────

class TestUpload:
    def test_success_returns_status_success(self, adapter, mock_anthropic_client):
        mock_anthropic_client.beta.files.upload.return_value = MagicMock(id="file-ant-abc")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            result = adapter.upload(b"document content", "doc.txt", "text/plain", {})

        assert result["status"] == "success"

    def test_success_returns_file_id(self, adapter, mock_anthropic_client):
        mock_anthropic_client.beta.files.upload.return_value = MagicMock(id="file-ant-abc")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            result = adapter.upload(b"content", "f.txt", "text/plain", {})

        assert result["file_id"] == "file-ant-abc"

    def test_success_returns_platform_anthropic(self, adapter, mock_anthropic_client):
        mock_anthropic_client.beta.files.upload.return_value = MagicMock(id="file-abc")

        with patch.object(adapter, "_check_dedup", return_value=None), \
             patch.object(adapter, "_store_dedup"):
            result = adapter.upload(b"data", "f.txt", "text/plain", {})

        assert result["platform"] == "anthropic"

    def test_duplicate_returns_skipped(self, adapter):
        with patch.object(adapter, "_check_dedup", return_value="file-cached"):
            result = adapter.upload(b"data", "f.txt", "text/plain", {})

        assert result["status"] == "skipped"
        assert result["file_id"] == "file-cached"

    def test_api_error_reraises(self, adapter, mock_anthropic_client):
        import anthropic as ant
        mock_anthropic_client.beta.files.upload.side_effect = ant.APIError(
            message="rate limit", request=MagicMock(), body=None
        )
        with patch.object(adapter, "_check_dedup", return_value=None):
            with pytest.raises(ant.APIError):
                adapter.upload(b"data", "f.txt", "text/plain", {})


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_success_returns_true(self, adapter, mock_anthropic_client):
        assert adapter.delete("file-abc") is True

    def test_api_error_returns_false(self, adapter, mock_anthropic_client):
        mock_anthropic_client.beta.files.delete.side_effect = Exception("not found")
        assert adapter.delete("file-abc") is False


# ── health_check ──────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_healthy_when_api_reachable(self, adapter, mock_anthropic_client):
        result = adapter.health_check()
        assert result["status"] == "healthy"
        assert result["platform"] == "anthropic"

    def test_unhealthy_when_api_fails(self, adapter, mock_anthropic_client):
        mock_anthropic_client.beta.files.list.side_effect = Exception("unauthorized")
        result = adapter.health_check()
        assert result["status"] == "unhealthy"
        assert "error" in result


# ── list_resources ────────────────────────────────────────────────────────────

class TestListResources:
    def test_returns_list(self, adapter, mock_anthropic_client):
        f = MagicMock(id="f1", filename="doc.txt", created_at=1234567890)
        mock_anthropic_client.beta.files.list.return_value = MagicMock(data=[f])
        result = adapter.list_resources()
        assert isinstance(result, list)
        assert result[0]["id"] == "f1"

    def test_api_error_returns_empty_list(self, adapter, mock_anthropic_client):
        mock_anthropic_client.beta.files.list.side_effect = Exception("error")
        assert adapter.list_resources() == []
