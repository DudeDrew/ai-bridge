# --------------------------
# utils/validator.py
# --------------------------
import hmac
from typing import Dict, Any

SUPPORTED_SOURCE_TYPES = ("notion", "obsidian", "github")
SUPPORTED_PLATFORMS = ("openai", "anthropic", "pinecone")


def validate_webhook_config(config: Dict[str, Any]) -> None:
    """
    Validate a webhook configuration dict.
    Raises ValueError with a descriptive message on the first validation failure.
    """
    if not isinstance(config, dict):
        raise ValueError("Webhook config must be a JSON object")

    # ── Source ────────────────────────────────────────────────────────────────
    source = config.get("source")
    if not source or not isinstance(source, dict):
        raise ValueError("'source' is required and must be an object")

    source_type = source.get("type")
    if not source_type:
        raise ValueError("'source.type' is required")
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(
            f"'source.type' must be one of: {', '.join(SUPPORTED_SOURCE_TYPES)}"
        )

    if source_type == "notion" and not source.get("database_id"):
        raise ValueError("'source.database_id' is required for Notion sources")

    if source_type == "obsidian" and not source.get("vault_name"):
        raise ValueError("'source.vault_name' is required for Obsidian sources")

    # ── Destination ───────────────────────────────────────────────────────────
    destination = config.get("destination")
    if not destination or not isinstance(destination, dict):
        raise ValueError("'destination' is required and must be an object")

    platform = destination.get("platform")
    if not platform:
        raise ValueError("'destination.platform' is required")
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(
            f"'destination.platform' must be one of: {', '.join(SUPPORTED_PLATFORMS)}"
        )

    if platform == "openai" and not destination.get("vector_store_id"):
        raise ValueError("'destination.vector_store_id' is required for OpenAI destinations")

    if platform == "pinecone" and not destination.get("index_name"):
        raise ValueError("'destination.index_name' is required for Pinecone destinations")

    # ── Optional fields ───────────────────────────────────────────────────────
    poll_interval = source.get("poll_interval")
    if poll_interval is not None:
        if not isinstance(poll_interval, int) or poll_interval < 60:
            raise ValueError("'source.poll_interval' must be an integer >= 60 (seconds)")


def validate_api_key(provided_key: str, expected_key: str) -> bool:
    """Constant-time comparison for API keys to prevent timing attacks."""
    return hmac.compare_digest(provided_key.encode(), expected_key.encode())
