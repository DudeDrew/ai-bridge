"""Tests for utils/validator.py — pure functions, no mocking required."""
import pytest
from utils.validator import validate_webhook_config, validate_api_key

# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_NOTION_OPENAI = {
    "source": {"type": "notion", "database_id": "abc123"},
    "destination": {"platform": "openai", "vector_store_id": "vs_abc"},
}

VALID_OBSIDIAN_PINECONE = {
    "source": {"type": "obsidian", "vault_name": "My Vault"},
    "destination": {"platform": "pinecone", "index_name": "my-index"},
}


# ── validate_webhook_config ───────────────────────────────────────────────────

class TestValidWebhookConfigs:
    def test_notion_openai_passes(self):
        validate_webhook_config(VALID_NOTION_OPENAI)  # must not raise

    def test_obsidian_pinecone_passes(self):
        validate_webhook_config(VALID_OBSIDIAN_PINECONE)

    def test_anthropic_needs_no_extra_destination_fields(self):
        validate_webhook_config({
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "anthropic"},
        })

    def test_optional_name_field_is_allowed(self):
        validate_webhook_config({**VALID_NOTION_OPENAI, "name": "My Connection"})

    def test_optional_enabled_field_is_allowed(self):
        validate_webhook_config({**VALID_NOTION_OPENAI, "enabled": False})

    def test_poll_interval_of_60_is_valid(self):
        config = {
            **VALID_NOTION_OPENAI,
            "source": {**VALID_NOTION_OPENAI["source"], "poll_interval": 60},
        }
        validate_webhook_config(config)

    def test_poll_interval_above_minimum_is_valid(self):
        config = {
            **VALID_NOTION_OPENAI,
            "source": {**VALID_NOTION_OPENAI["source"], "poll_interval": 3600},
        }
        validate_webhook_config(config)


class TestMissingOrInvalidTopLevel:
    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            validate_webhook_config(["source", "destination"])

    def test_none_raises(self):
        with pytest.raises(ValueError, match="JSON object"):
            validate_webhook_config(None)

    def test_missing_source_raises(self):
        with pytest.raises(ValueError, match="'source'"):
            validate_webhook_config({"destination": {"platform": "openai"}})

    def test_source_as_string_raises(self):
        with pytest.raises(ValueError, match="'source'"):
            validate_webhook_config({"source": "notion", "destination": {"platform": "openai"}})

    def test_missing_destination_raises(self):
        with pytest.raises(ValueError, match="'destination'"):
            validate_webhook_config({"source": {"type": "notion", "database_id": "db1"}})

    def test_destination_as_string_raises(self):
        with pytest.raises(ValueError, match="'destination'"):
            validate_webhook_config({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": "openai",
            })


class TestSourceValidation:
    def test_missing_source_type_raises(self):
        with pytest.raises(ValueError, match="'source.type'"):
            validate_webhook_config({
                "source": {},
                "destination": {"platform": "openai", "vector_store_id": "vs"},
            })

    def test_unsupported_source_type_raises(self):
        with pytest.raises(ValueError, match="'source.type'"):
            validate_webhook_config({
                "source": {"type": "dropbox"},
                "destination": {"platform": "openai", "vector_store_id": "vs"},
            })

    def test_notion_missing_database_id_raises(self):
        with pytest.raises(ValueError, match="database_id"):
            validate_webhook_config({
                "source": {"type": "notion"},
                "destination": {"platform": "openai", "vector_store_id": "vs"},
            })

    def test_obsidian_missing_vault_name_raises(self):
        with pytest.raises(ValueError, match="vault_name"):
            validate_webhook_config({
                "source": {"type": "obsidian"},
                "destination": {"platform": "pinecone", "index_name": "idx"},
            })

    def test_poll_interval_below_minimum_raises(self):
        config = {
            **VALID_NOTION_OPENAI,
            "source": {**VALID_NOTION_OPENAI["source"], "poll_interval": 30},
        }
        with pytest.raises(ValueError, match="poll_interval"):
            validate_webhook_config(config)

    def test_poll_interval_zero_raises(self):
        config = {
            **VALID_NOTION_OPENAI,
            "source": {**VALID_NOTION_OPENAI["source"], "poll_interval": 0},
        }
        with pytest.raises(ValueError, match="poll_interval"):
            validate_webhook_config(config)

    def test_poll_interval_as_string_raises(self):
        config = {
            **VALID_NOTION_OPENAI,
            "source": {**VALID_NOTION_OPENAI["source"], "poll_interval": "hourly"},
        }
        with pytest.raises(ValueError, match="poll_interval"):
            validate_webhook_config(config)

    def test_poll_interval_as_float_raises(self):
        config = {
            **VALID_NOTION_OPENAI,
            "source": {**VALID_NOTION_OPENAI["source"], "poll_interval": 3600.0},
        }
        with pytest.raises(ValueError, match="poll_interval"):
            validate_webhook_config(config)


class TestDestinationValidation:
    def test_missing_platform_raises(self):
        with pytest.raises(ValueError, match="'destination.platform'"):
            validate_webhook_config({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": {},
            })

    def test_unsupported_platform_raises(self):
        with pytest.raises(ValueError, match="'destination.platform'"):
            validate_webhook_config({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": {"platform": "mistral"},
            })

    def test_openai_missing_vector_store_id_raises(self):
        with pytest.raises(ValueError, match="vector_store_id"):
            validate_webhook_config({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": {"platform": "openai"},
            })

    def test_pinecone_missing_index_name_raises(self):
        with pytest.raises(ValueError, match="index_name"):
            validate_webhook_config({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": {"platform": "pinecone"},
            })


# ── validate_api_key ──────────────────────────────────────────────────────────

class TestValidateApiKey:
    def test_matching_keys_returns_true(self):
        assert validate_api_key("my-secret-key", "my-secret-key") is True

    def test_mismatched_keys_returns_false(self):
        assert validate_api_key("wrong-key", "my-secret-key") is False

    def test_empty_provided_key_returns_false(self):
        assert validate_api_key("", "my-secret-key") is False

    def test_empty_expected_key_returns_false(self):
        assert validate_api_key("my-key", "") is False

    def test_both_empty_returns_true(self):
        # hmac.compare_digest("", "") is True — consistent behaviour
        assert validate_api_key("", "") is True

    def test_case_sensitive(self):
        assert validate_api_key("Key", "key") is False
