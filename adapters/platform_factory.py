# --------------------------
# adapters/platform_factory.py
# --------------------------
import logging
from typing import Dict, Any

from .base_adapter import BasePlatformAdapter

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = ("openai", "anthropic", "pinecone")


class PlatformFactory:
    """Instantiates the correct platform adapter given a platform name string."""

    @staticmethod
    def create(platform: str, config: Dict[str, Any]) -> BasePlatformAdapter:
        """
        Create and return a platform adapter.

        :param platform: One of 'openai', 'anthropic', 'pinecone'
        :param config: Adapter-specific configuration dict
        :raises ValueError: If the platform name is not supported
        """
        platform = platform.lower()

        if platform == "openai":
            from .openai_adapter import OpenAIAdapter
            return OpenAIAdapter(config)
        elif platform == "anthropic":
            from .anthropic_adapter import AnthropicAdapter
            return AnthropicAdapter(config)
        elif platform == "pinecone":
            from .pinecone_adapter import PineconeAdapter
            return PineconeAdapter(config)
        else:
            raise ValueError(
                f"Unsupported platform '{platform}'. "
                f"Supported: {', '.join(SUPPORTED_PLATFORMS)}"
            )

    @staticmethod
    def supported_platforms() -> tuple:
        """Return the tuple of supported platform identifiers."""
        return SUPPORTED_PLATFORMS
