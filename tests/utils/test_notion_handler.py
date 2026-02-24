"""Tests for utils/notion_handler.py."""
import pytest
from unittest.mock import MagicMock, patch, call


# ── _rich_text_to_str ─────────────────────────────────────────────────────────

class TestRichTextToStr:
    def test_concatenates_plain_text_segments(self):
        from utils.notion_handler import _rich_text_to_str
        rt = [{"plain_text": "Hello "}, {"plain_text": "world"}]
        assert _rich_text_to_str(rt) == "Hello world"

    def test_empty_list_returns_empty_string(self):
        from utils.notion_handler import _rich_text_to_str
        assert _rich_text_to_str([]) == ""

    def test_missing_plain_text_key_treated_as_empty(self):
        from utils.notion_handler import _rich_text_to_str
        rt = [{"type": "mention", "mention": {}}]
        assert _rich_text_to_str(rt) == ""

    def test_single_segment(self):
        from utils.notion_handler import _rich_text_to_str
        assert _rich_text_to_str([{"plain_text": "Solo"}]) == "Solo"


# ── _block_to_text ────────────────────────────────────────────────────────────

class TestBlockToText:
    def _rt(self, text):
        return [{"plain_text": text}]

    def test_paragraph(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "paragraph", "paragraph": {"rich_text": self._rt("Hello")}}
        assert _block_to_text(block) == "Hello"

    def test_heading_1(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "heading_1", "heading_1": {"rich_text": self._rt("Title")}}
        assert _block_to_text(block) == "Title"

    def test_heading_2(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "heading_2", "heading_2": {"rich_text": self._rt("Sub")}}
        assert _block_to_text(block) == "Sub"

    def test_bulleted_list_item(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "bulleted_list_item",
                 "bulleted_list_item": {"rich_text": self._rt("Item")}}
        assert _block_to_text(block) == "Item"

    def test_divider_returns_dashes(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "divider", "divider": {}}
        assert _block_to_text(block) == "---"

    def test_code_block_includes_language(self):
        from utils.notion_handler import _block_to_text
        block = {
            "type": "code",
            "code": {"language": "python", "rich_text": self._rt('print("hi")')},
        }
        result = _block_to_text(block)
        assert "```python" in result
        assert 'print("hi")' in result

    def test_to_do_unchecked(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "to_do", "to_do": {"checked": False, "rich_text": self._rt("Task")}}
        assert _block_to_text(block) == "[ ] Task"

    def test_to_do_checked(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "to_do", "to_do": {"checked": True, "rich_text": self._rt("Done")}}
        assert _block_to_text(block) == "[x] Done"

    def test_unsupported_block_type_returns_empty_string(self):
        from utils.notion_handler import _block_to_text
        block = {"type": "image", "image": {"type": "external", "external": {"url": "..."}}}
        assert _block_to_text(block) == ""


# ── _get_client ───────────────────────────────────────────────────────────────

class TestGetClient:
    def test_no_token_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        from utils.notion_handler import _get_client
        with pytest.raises(RuntimeError, match="NOTION_TOKEN"):
            _get_client()

    def test_with_token_returns_client(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")
        with patch("utils.notion_handler.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from utils.notion_handler import _get_client
            client = _get_client()
            mock_cls.assert_called_once_with(auth="secret_test")


# ── fetch_notion_page ─────────────────────────────────────────────────────────

class TestFetchNotionPage:
    def _make_page(self, title_text="My Page"):
        return {
            "id": "page-id",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": title_text}]}
            },
        }

    def _make_blocks_response(self, texts):
        return {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": t}]},
                    "has_children": False,
                    "id": f"block-{i}",
                }
                for i, t in enumerate(texts)
            ],
            "has_more": False,
        }

    def test_title_in_output(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")
        with patch("utils.notion_handler.Client") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.pages.retrieve.return_value = self._make_page("Report Title")
            client.blocks.children.list.return_value = self._make_blocks_response(["Body"])

            from utils.notion_handler import fetch_notion_page
            result = fetch_notion_page("page-id")

        assert "Report Title" in result

    def test_body_text_in_output(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")
        with patch("utils.notion_handler.Client") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.pages.retrieve.return_value = self._make_page()
            client.blocks.children.list.return_value = self._make_blocks_response(
                ["First paragraph", "Second paragraph"]
            )

            from utils.notion_handler import fetch_notion_page
            result = fetch_notion_page("page-id")

        assert "First paragraph" in result

    def test_result_starts_with_h1(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")
        with patch("utils.notion_handler.Client") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.pages.retrieve.return_value = self._make_page("Title")
            client.blocks.children.list.return_value = self._make_blocks_response([])

            from utils.notion_handler import fetch_notion_page
            result = fetch_notion_page("page-id")

        assert result.startswith("# Title")


# ── fetch_notion_database ─────────────────────────────────────────────────────

class TestFetchNotionDatabase:
    def test_returns_list_of_dicts(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")
        with patch("utils.notion_handler.Client") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client

            page = {
                "id": "pg-1",
                "properties": {
                    "title": {"type": "title", "title": [{"plain_text": "Page One"}]}
                },
            }
            client.databases.query.return_value = {"results": [page], "has_more": False}
            client.blocks.children.list.return_value = {
                "results": [
                    {
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"plain_text": "Content"}]},
                        "has_children": False,
                        "id": "b1",
                    }
                ],
                "has_more": False,
            }

            from utils.notion_handler import fetch_notion_database
            result = fetch_notion_database("db-id")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == "pg-1"
        assert result[0]["title"] == "Page One"
        assert "Content" in result[0]["content"]

    def test_empty_database_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")
        with patch("utils.notion_handler.Client") as mock_cls:
            client = MagicMock()
            mock_cls.return_value = client
            client.databases.query.return_value = {"results": [], "has_more": False}

            from utils.notion_handler import fetch_notion_database
            result = fetch_notion_database("db-id")

        assert result == []
