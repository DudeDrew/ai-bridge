"""Tests for adapters/base_adapter.py."""
import pytest
from adapters.base_adapter import BasePlatformAdapter


# ── Minimal concrete subclass for testing non-abstract methods ────────────────

class ConcreteAdapter(BasePlatformAdapter):
    """Trivial implementation that satisfies all abstract methods."""
    def upload(self, content, filename, content_type, metadata):
        return {"status": "success"}

    def fetch(self, resource_id):
        return b"content"

    def delete(self, resource_id):
        return True

    def list_resources(self):
        return []

    def validate_config(self):
        return True

    def health_check(self):
        return {"status": "healthy", "platform": "test"}


@pytest.fixture
def adapter():
    return ConcreteAdapter({"api_key": "test-key"})


# ── Instantiation ─────────────────────────────────────────────────────────────

class TestInstantiation:
    def test_cannot_instantiate_base_class_directly(self):
        with pytest.raises(TypeError):
            BasePlatformAdapter({})

    def test_concrete_subclass_stores_config(self, adapter):
        assert adapter.config == {"api_key": "test-key"}

    def test_concrete_subclass_has_logger(self, adapter):
        import logging
        assert isinstance(adapter.logger, logging.Logger)

    def test_logger_named_after_class(self, adapter):
        assert adapter.logger.name == "ConcreteAdapter"


# ── get_dedup_key ─────────────────────────────────────────────────────────────

class TestGetDedupKey:
    def test_returns_a_string(self, adapter):
        key = adapter.get_dedup_key(b"hello", "file.txt")
        assert isinstance(key, str)

    def test_includes_filename(self, adapter):
        key = adapter.get_dedup_key(b"content", "myfile.txt")
        assert "myfile.txt" in key

    def test_deterministic_same_inputs(self, adapter):
        key1 = adapter.get_dedup_key(b"data", "f.txt")
        key2 = adapter.get_dedup_key(b"data", "f.txt")
        assert key1 == key2

    def test_different_content_produces_different_key(self, adapter):
        key1 = adapter.get_dedup_key(b"content A", "f.txt")
        key2 = adapter.get_dedup_key(b"content B", "f.txt")
        assert key1 != key2

    def test_different_filename_produces_different_key(self, adapter):
        key1 = adapter.get_dedup_key(b"same content", "a.txt")
        key2 = adapter.get_dedup_key(b"same content", "b.txt")
        assert key1 != key2

    def test_empty_content_is_handled(self, adapter):
        key = adapter.get_dedup_key(b"", "empty.txt")
        assert isinstance(key, str)
        assert len(key) > 0

    def test_key_format_is_filename_colon_hash(self, adapter):
        key = adapter.get_dedup_key(b"data", "report.md")
        parts = key.split(":")
        assert parts[0] == "report.md"
        assert len(parts[1]) == 16  # 16-char hex hash
