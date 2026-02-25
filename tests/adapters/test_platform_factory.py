"""Tests for adapters/platform_factory.py."""
import pytest
from unittest.mock import patch, MagicMock


class TestPlatformFactoryCreate:
    def test_openai_returns_openai_adapter(self):
        with patch("adapters.openai_adapter.OpenAI"):
            from adapters.platform_factory import PlatformFactory
            from adapters.openai_adapter import OpenAIAdapter
            adapter = PlatformFactory.create(
                "openai", {"api_key": "sk-test", "vector_store_id": "vs_test"}
            )
            assert isinstance(adapter, OpenAIAdapter)

    def test_anthropic_returns_anthropic_adapter(self):
        with patch("adapters.anthropic_adapter.anthropic.Anthropic"):
            from adapters.platform_factory import PlatformFactory
            from adapters.anthropic_adapter import AnthropicAdapter
            adapter = PlatformFactory.create(
                "anthropic", {"api_key": "sk-ant-test"}
            )
            assert isinstance(adapter, AnthropicAdapter)

    def test_pinecone_returns_pinecone_adapter(self):
        with patch("adapters.pinecone_adapter.Pinecone"), \
             patch("adapters.pinecone_adapter.OpenAI"):
            from adapters.platform_factory import PlatformFactory
            from adapters.pinecone_adapter import PineconeAdapter
            adapter = PlatformFactory.create(
                "pinecone", {"api_key": "pc-test", "index_name": "my-index"}
            )
            assert isinstance(adapter, PineconeAdapter)

    def test_platform_name_is_case_insensitive(self):
        with patch("adapters.openai_adapter.OpenAI"):
            from adapters.platform_factory import PlatformFactory
            from adapters.openai_adapter import OpenAIAdapter
            adapter = PlatformFactory.create(
                "OpenAI", {"api_key": "sk-test", "vector_store_id": "vs_test"}
            )
            assert isinstance(adapter, OpenAIAdapter)

    def test_unsupported_platform_raises_value_error(self):
        from adapters.platform_factory import PlatformFactory
        with pytest.raises(ValueError, match="Unsupported platform"):
            PlatformFactory.create("mistral", {})

    def test_error_message_names_the_bad_platform(self):
        from adapters.platform_factory import PlatformFactory
        with pytest.raises(ValueError, match="badplatform"):
            PlatformFactory.create("badplatform", {})

    def test_empty_string_raises_value_error(self):
        from adapters.platform_factory import PlatformFactory
        with pytest.raises(ValueError):
            PlatformFactory.create("", {})


class TestSupportedPlatforms:
    def test_returns_a_tuple(self):
        from adapters.platform_factory import PlatformFactory
        result = PlatformFactory.supported_platforms()
        assert isinstance(result, tuple)

    def test_contains_openai(self):
        from adapters.platform_factory import PlatformFactory
        assert "openai" in PlatformFactory.supported_platforms()

    def test_contains_anthropic(self):
        from adapters.platform_factory import PlatformFactory
        assert "anthropic" in PlatformFactory.supported_platforms()

    def test_contains_pinecone(self):
        from adapters.platform_factory import PlatformFactory
        assert "pinecone" in PlatformFactory.supported_platforms()
