"""Tests for utils/webhook_generator.py."""
import pytest
from unittest.mock import MagicMock, patch, call


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_webhook.return_value = None
    db.get_all_webhooks.return_value = {}
    db.get_dedup.return_value = None
    return db


@pytest.fixture
def generator(mock_db):
    from utils.webhook_generator import WebhookGenerator
    return WebhookGenerator(mock_db)


@pytest.fixture
def notion_webhook():
    return {
        "id": "abc12345",
        "source": {"type": "notion", "database_id": "db-001"},
        "destination": {"platform": "openai", "vector_store_id": "vs-001"},
        "enabled": True,
    }


@pytest.fixture
def obsidian_webhook():
    return {
        "id": "def67890",
        "source": {"type": "obsidian", "vault_name": "Research"},
        "destination": {"platform": "openai", "vector_store_id": "vs-001"},
        "enabled": True,
    }


# ── create_webhook ────────────────────────────────────────────────────────────

class TestCreateWebhook:
    def test_returns_8_character_id(self, generator, mock_db):
        webhook_id = generator.create_webhook({"source": {}, "destination": {}})
        assert len(webhook_id) == 8

    def test_id_is_alphanumeric(self, generator, mock_db):
        webhook_id = generator.create_webhook({"source": {}, "destination": {}})
        assert webhook_id.isalnum() or "-" in webhook_id  # UUID chars

    def test_saves_config_to_db(self, generator, mock_db):
        generator.create_webhook({"source": {}, "destination": {}})
        mock_db.save_webhook.assert_called_once()

    def test_saved_config_includes_id(self, generator, mock_db):
        webhook_id = generator.create_webhook({"source": {}, "destination": {}})
        saved_id, saved_config = mock_db.save_webhook.call_args[0]
        assert saved_config["id"] == webhook_id

    def test_saved_config_includes_created_at(self, generator, mock_db):
        generator.create_webhook({"source": {}, "destination": {}})
        _, saved_config = mock_db.save_webhook.call_args[0]
        assert "created_at" in saved_config

    def test_enabled_defaults_to_true(self, generator, mock_db):
        generator.create_webhook({"source": {}, "destination": {}})
        _, saved_config = mock_db.save_webhook.call_args[0]
        assert saved_config["enabled"] is True

    def test_respects_explicit_enabled_false(self, generator, mock_db):
        generator.create_webhook({"source": {}, "destination": {}, "enabled": False})
        _, saved_config = mock_db.save_webhook.call_args[0]
        assert saved_config["enabled"] is False

    def test_each_call_produces_unique_id(self, generator, mock_db):
        ids = {generator.create_webhook({"source": {}, "destination": {}}) for _ in range(10)}
        assert len(ids) == 10


# ── delete_webhook ────────────────────────────────────────────────────────────

class TestDeleteWebhook:
    def test_delegates_to_db(self, generator, mock_db):
        generator.delete_webhook("abc12345")
        mock_db.delete_webhook.assert_called_once_with("abc12345")


# ── process_incoming_webhook ──────────────────────────────────────────────────

class TestProcessIncomingWebhook:
    def test_missing_webhook_raises_value_error(self, generator, mock_db):
        mock_db.get_webhook.return_value = None
        with pytest.raises(ValueError, match="not found"):
            generator.process_incoming_webhook("missing-id", {})

    def test_disabled_webhook_returns_disabled_status(self, generator, mock_db):
        mock_db.get_webhook.return_value = {
            "id": "abc", "enabled": False, "source": {}, "destination": {}
        }
        result = generator.process_incoming_webhook("abc", {})
        assert result["status"] == "disabled"

    def test_disabled_webhook_does_not_call_adapter(self, generator, mock_db):
        mock_db.get_webhook.return_value = {
            "id": "abc", "enabled": False, "source": {}, "destination": {}
        }
        with patch("utils.webhook_generator.PlatformFactory") as mock_factory:
            generator.process_incoming_webhook("abc", {})
            mock_factory.create.assert_not_called()

    def test_enabled_webhook_calls_adapter_upload(self, generator, mock_db):
        mock_db.get_webhook.return_value = {
            "id": "abc", "enabled": True,
            "source": {"type": "notion"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        mock_adapter = MagicMock()
        mock_adapter.upload.return_value = {"status": "success"}

        with patch("utils.webhook_generator.PlatformFactory.create", return_value=mock_adapter):
            result = generator.process_incoming_webhook("abc", {"content": "hello"})

        mock_adapter.upload.assert_called_once()
        assert result["status"] == "success"

    def test_sync_event_logged_after_processing(self, generator, mock_db):
        mock_db.get_webhook.return_value = {
            "id": "abc", "enabled": True,
            "source": {"type": "notion"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        mock_adapter = MagicMock()
        mock_adapter.upload.return_value = {"status": "success"}

        with patch("utils.webhook_generator.PlatformFactory.create", return_value=mock_adapter):
            generator.process_incoming_webhook("abc", {"content": "data"})

        mock_db.log_sync.assert_called_once()


# ── trigger_webhook ───────────────────────────────────────────────────────────

class TestTriggerWebhook:
    def test_missing_webhook_raises_value_error(self, generator, mock_db):
        mock_db.get_webhook.return_value = None
        with pytest.raises(ValueError, match="not found"):
            generator.trigger_webhook("ghost")

    def test_notion_source_calls_sync_notion(self, generator, mock_db, notion_webhook):
        mock_db.get_webhook.return_value = notion_webhook
        with patch.object(
            generator, "_sync_notion",
            return_value={"status": "synced", "pages_processed": 0, "results": []}
        ) as mock_sync:
            generator.trigger_webhook("abc12345")
            mock_sync.assert_called_once_with(notion_webhook)

    def test_obsidian_source_calls_sync_obsidian(self, generator, mock_db, obsidian_webhook):
        mock_db.get_webhook.return_value = obsidian_webhook
        with patch.object(
            generator, "_sync_obsidian",
            return_value={"status": "synced", "notes_processed": 0, "results": []}
        ) as mock_sync:
            generator.trigger_webhook("def67890")
            mock_sync.assert_called_once_with(obsidian_webhook)

    def test_github_source_raises_not_implemented(self, generator, mock_db):
        mock_db.get_webhook.return_value = {
            "id": "abc", "source": {"type": "github"}, "destination": {}
        }
        with pytest.raises(NotImplementedError):
            generator.trigger_webhook("abc")

    def test_unknown_source_type_raises_value_error(self, generator, mock_db):
        mock_db.get_webhook.return_value = {
            "id": "abc", "source": {"type": "dropbox"}, "destination": {}
        }
        with pytest.raises(ValueError, match="Unsupported source type"):
            generator.trigger_webhook("abc")

    def test_sync_event_logged_after_trigger(self, generator, mock_db, notion_webhook):
        mock_db.get_webhook.return_value = notion_webhook
        with patch.object(
            generator, "_sync_notion",
            return_value={"status": "synced", "pages_processed": 2, "results": []}
        ):
            generator.trigger_webhook("abc12345")

        mock_db.log_sync.assert_called_once()


# ── _sync_notion ──────────────────────────────────────────────────────────────

class TestSyncNotion:
    def test_missing_database_id_raises(self, generator):
        webhook = {"id": "abc", "source": {"type": "notion"}, "destination": {"platform": "openai"}}
        with pytest.raises(ValueError, match="database_id"):
            generator._sync_notion(webhook)

    def test_returns_synced_status(self, generator):
        webhook = {
            "id": "abc",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        pages = [{"id": "p1", "title": "Page 1", "content": "Content"}]
        mock_adapter = MagicMock()
        mock_adapter.upload.return_value = {"status": "success", "file_id": "f1"}

        with patch("utils.webhook_generator.PlatformFactory.create", return_value=mock_adapter), \
             patch("utils.notion_handler.fetch_notion_database", return_value=pages):
            result = generator._sync_notion(webhook)

        assert result["status"] == "synced"

    def test_pages_processed_count_matches_pages(self, generator):
        webhook = {
            "id": "abc",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        pages = [
            {"id": "p1", "title": "Page 1", "content": "A"},
            {"id": "p2", "title": "Page 2", "content": "B"},
        ]
        mock_adapter = MagicMock()
        mock_adapter.upload.return_value = {"status": "success"}

        with patch("utils.webhook_generator.PlatformFactory.create", return_value=mock_adapter), \
             patch("utils.notion_handler.fetch_notion_database", return_value=pages):
            result = generator._sync_notion(webhook)

        assert result["pages_processed"] == 2

    def test_individual_upload_error_recorded_in_results(self, generator):
        webhook = {
            "id": "abc",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        pages = [{"id": "p1", "title": "Bad Page", "content": "X"}]
        mock_adapter = MagicMock()
        mock_adapter.upload.side_effect = Exception("upload failed")

        with patch("utils.webhook_generator.PlatformFactory.create", return_value=mock_adapter), \
             patch("utils.notion_handler.fetch_notion_database", return_value=pages):
            result = generator._sync_notion(webhook)

        assert result["results"][0]["status"] == "error"


# ── _sync_obsidian ────────────────────────────────────────────────────────────

class TestSyncObsidian:
    def test_returns_error_dict_when_vault_unreachable(self, generator):
        webhook = {
            "id": "abc",
            "source": {"type": "obsidian", "vault_name": "Vault"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        with patch("utils.obsidian_handler.fetch_obsidian_vault",
                   side_effect=RuntimeError("connection refused")):
            result = generator._sync_obsidian(webhook)

        assert result["status"] == "error"
        assert "error" in result

    def test_returns_synced_status_on_success(self, generator):
        webhook = {
            "id": "abc",
            "source": {"type": "obsidian", "vault_name": "Vault"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        notes = [{"id": "n/a.md", "title": "Alpha", "content": "Content A"}]
        mock_adapter = MagicMock()
        mock_adapter.upload.return_value = {"status": "success"}

        with patch("utils.webhook_generator.PlatformFactory.create", return_value=mock_adapter), \
             patch("utils.obsidian_handler.fetch_obsidian_vault", return_value=notes):
            result = generator._sync_obsidian(webhook)

        assert result["status"] == "synced"
        assert result["notes_processed"] == 1


# ── start / stop ──────────────────────────────────────────────────────────────

class TestStartStop:
    def test_start_does_not_launch_threads_for_webhooks_without_poll_interval(
        self, generator, mock_db
    ):
        mock_db.get_all_webhooks.return_value = {
            "abc": {"enabled": True, "source": {}}  # no poll_interval
        }
        with patch.object(generator, "_start_poll_thread") as mock_thread:
            generator.start()
            mock_thread.assert_not_called()

    def test_start_launches_thread_for_enabled_webhook_with_poll_interval(
        self, generator, mock_db
    ):
        mock_db.get_all_webhooks.return_value = {
            "abc": {"enabled": True, "source": {"poll_interval": 300}}
        }
        with patch.object(generator, "_start_poll_thread") as mock_thread:
            generator.start()
            mock_thread.assert_called_once_with("abc")

    def test_start_skips_disabled_webhooks(self, generator, mock_db):
        mock_db.get_all_webhooks.return_value = {
            "abc": {"enabled": False, "source": {"poll_interval": 300}}
        }
        with patch.object(generator, "_start_poll_thread") as mock_thread:
            generator.start()
            mock_thread.assert_not_called()

    def test_start_is_idempotent(self, generator, mock_db):
        mock_db.get_all_webhooks.return_value = {}
        generator.start()
        generator.start()  # second call should be a no-op
        assert generator.running is True

    def test_stop_sets_running_false(self, generator, mock_db):
        mock_db.get_all_webhooks.return_value = {}
        generator.start()
        generator.stop()
        assert generator.running is False
