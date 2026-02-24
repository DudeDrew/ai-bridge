"""Tests for utils/obsidian_handler.py."""
import json
import pytest
from unittest.mock import MagicMock, patch


# ── _get_headers ──────────────────────────────────────────────────────────────

class TestGetHeaders:
    def test_no_api_key_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_API_KEY", raising=False)
        from utils.obsidian_handler import _get_headers
        with pytest.raises(RuntimeError, match="OBSIDIAN_API_KEY"):
            _get_headers()

    def test_returns_authorization_header(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "my-key")
        from utils.obsidian_handler import _get_headers
        headers = _get_headers()
        assert headers["Authorization"] == "Bearer my-key"


# ── _get_base_url ─────────────────────────────────────────────────────────────

class TestGetBaseUrl:
    def test_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://192.168.1.5:27123")
        from utils.obsidian_handler import _get_base_url
        assert _get_base_url() == "http://192.168.1.5:27123"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123/")
        from utils.obsidian_handler import _get_base_url
        assert not _get_base_url().endswith("/")

    def test_default_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_API_URL", raising=False)
        from utils.obsidian_handler import _get_base_url
        assert _get_base_url() == "http://localhost:27123"


# ── fetch_obsidian_vault ──────────────────────────────────────────────────────

class TestFetchObsidianVault:
    def _mock_requests(self, files, note_content="# Note\n\nContent"):
        """Build side_effect list: first call lists files, rest return note content."""
        list_resp = MagicMock()
        list_resp.json.return_value = {"files": files}
        list_resp.raise_for_status = MagicMock()

        content_resp = MagicMock()
        content_resp.text = note_content
        content_resp.raise_for_status = MagicMock()

        return [list_resp] + [content_resp] * len(files)

    def test_returns_list_of_notes(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")
        files = ["notes/alpha.md", "notes/beta.md"]

        with patch("utils.obsidian_handler.requests.get") as mock_get:
            mock_get.side_effect = self._mock_requests(files)
            from utils.obsidian_handler import fetch_obsidian_vault
            notes = fetch_obsidian_vault("My Vault")

        assert len(notes) == 2

    def test_note_title_derived_from_filename(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")

        with patch("utils.obsidian_handler.requests.get") as mock_get:
            mock_get.side_effect = self._mock_requests(["folder/my-note.md"])
            from utils.obsidian_handler import fetch_obsidian_vault
            notes = fetch_obsidian_vault("Vault")

        assert notes[0]["title"] == "my-note"

    def test_note_id_is_file_path(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")

        with patch("utils.obsidian_handler.requests.get") as mock_get:
            mock_get.side_effect = self._mock_requests(["notes/hello.md"])
            from utils.obsidian_handler import fetch_obsidian_vault
            notes = fetch_obsidian_vault("Vault")

        assert notes[0]["id"] == "notes/hello.md"

    def test_note_content_returned(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")

        with patch("utils.obsidian_handler.requests.get") as mock_get:
            mock_get.side_effect = self._mock_requests(["n.md"], note_content="My Content")
            from utils.obsidian_handler import fetch_obsidian_vault
            notes = fetch_obsidian_vault("Vault")

        assert notes[0]["content"] == "My Content"

    def test_non_markdown_files_skipped(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")
        files_all = ["note.md", "image.png", "data.json"]

        list_resp = MagicMock()
        list_resp.json.return_value = {"files": files_all}
        list_resp.raise_for_status = MagicMock()

        content_resp = MagicMock()
        content_resp.text = "# Note"
        content_resp.raise_for_status = MagicMock()

        with patch("utils.obsidian_handler.requests.get") as mock_get:
            mock_get.side_effect = [list_resp, content_resp]
            from utils.obsidian_handler import fetch_obsidian_vault
            notes = fetch_obsidian_vault("Vault")

        assert len(notes) == 1  # only note.md

    def test_api_unreachable_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")
        import requests as req

        with patch("utils.obsidian_handler.requests.get",
                   side_effect=req.RequestException("connection refused")):
            from utils.obsidian_handler import fetch_obsidian_vault
            with pytest.raises(RuntimeError, match="Could not reach"):
                fetch_obsidian_vault("Vault")

    def test_individual_note_fetch_error_skipped(self, monkeypatch):
        """A 404 on one note should not abort the whole vault sync."""
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")
        import requests as req

        list_resp = MagicMock()
        list_resp.json.return_value = {"files": ["good.md", "bad.md"]}
        list_resp.raise_for_status = MagicMock()

        good_resp = MagicMock()
        good_resp.text = "Good content"
        good_resp.raise_for_status = MagicMock()

        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = req.RequestException("404 not found")

        with patch("utils.obsidian_handler.requests.get") as mock_get:
            mock_get.side_effect = [list_resp, good_resp, bad_resp]
            from utils.obsidian_handler import fetch_obsidian_vault
            notes = fetch_obsidian_vault("Vault")

        assert len(notes) == 1
        assert notes[0]["title"] == "good"


# ── process_obsidian_webhook ──────────────────────────────────────────────────

class TestProcessObsidianWebhook:
    def test_returns_content_field_directly(self):
        from utils.obsidian_handler import process_obsidian_webhook
        result = process_obsidian_webhook({"content": "My note text"})
        assert result == "My note text"

    def test_content_field_takes_priority_over_text(self):
        from utils.obsidian_handler import process_obsidian_webhook
        result = process_obsidian_webhook({"content": "Content", "text": "Text"})
        assert result == "Content"

    def test_falls_back_to_text_field(self):
        from utils.obsidian_handler import process_obsidian_webhook
        result = process_obsidian_webhook({"text": "Text content"})
        assert result == "Text content"

    def test_unknown_payload_returns_json_string(self):
        from utils.obsidian_handler import process_obsidian_webhook
        payload = {"event": "modified", "vault": "test"}
        result = process_obsidian_webhook(payload)
        parsed = json.loads(result)
        assert parsed == payload

    def test_path_field_fetches_content(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_API_KEY", "test-key")
        monkeypatch.setenv("OBSIDIAN_API_URL", "http://localhost:27123")

        content_resp = MagicMock()
        content_resp.text = "Fetched note content"
        content_resp.raise_for_status = MagicMock()

        with patch("utils.obsidian_handler.requests.get", return_value=content_resp):
            from utils.obsidian_handler import process_obsidian_webhook
            result = process_obsidian_webhook({"path": "notes/my-note.md"})

        assert result == "Fetched note content"
