# --------------------------
# utils/webhook_generator.py
# --------------------------
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, Any

import requests
from adapters.platform_factory import PlatformFactory

logger = logging.getLogger(__name__)


class WebhookGenerator:
    """
    Manages webhook lifecycle and polling.
    Monitors sources (Notion, Obsidian, GitHub) and pushes updates to destinations.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.running = False
        self.threads = []

    # ── Webhook CRUD ──────────────────────────────────────────────────────────

    def create_webhook(self, config: Dict[str, Any]) -> str:
        """Create a new webhook configuration and persist it."""
        webhook_id = str(uuid.uuid4())[:8]
        webhook_config = {
            **config,
            "id": webhook_id,
            "created_at": datetime.utcnow().isoformat(),
            "enabled": config.get("enabled", True),
        }
        self.db.save_webhook(webhook_id, webhook_config)
        logger.info(f"Created webhook: {webhook_id}")
        return webhook_id

    def delete_webhook(self, webhook_id: str):
        """Delete a webhook configuration."""
        self.db.delete_webhook(webhook_id)
        logger.info(f"Deleted webhook: {webhook_id}")

    # ── Inbound webhook processing ────────────────────────────────────────────

    def process_incoming_webhook(self, webhook_id: str, payload: Dict) -> Dict:
        """Process an incoming webhook payload and forward content to the destination."""
        webhook = self.db.get_webhook(webhook_id)
        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")

        if not webhook.get("enabled", True):
            return {"status": "disabled"}

        content = self._extract_content(payload, webhook.get("source", {}))

        destination = webhook.get("destination", {})
        platform = destination.get("platform", "openai")
        adapter = PlatformFactory.create(platform, destination)

        result = adapter.upload(
            content=content.encode("utf-8"),
            filename=f"webhook_{webhook_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt",
            content_type="text/plain",
            metadata={
                "webhook_id": webhook_id,
                "received_at": datetime.utcnow().isoformat(),
                "source": webhook.get("source", {}).get("type", "unknown"),
            },
        )

        status = result.get("status", "unknown")
        self.db.log_sync(
            webhook_id=webhook_id,
            status=status,
            items_processed=1 if status == "success" else 0,
            items_failed=1 if status not in ("success", "skipped") else 0,
            details=result,
        )

        logger.info(f"Processed incoming webhook {webhook_id}: {result}")
        return result

    # ── Manual / polling trigger ──────────────────────────────────────────────

    def trigger_webhook(self, webhook_id: str) -> Dict:
        """Manually trigger a webhook — polls the source and syncs to destination."""
        webhook = self.db.get_webhook(webhook_id)
        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")

        source_type = webhook.get("source", {}).get("type")

        if source_type == "notion":
            result = self._sync_notion(webhook)
        elif source_type == "obsidian":
            result = self._sync_obsidian(webhook)
        elif source_type == "github":
            result = self._sync_github(webhook)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        # Log the sync event
        status = result.get("status", "unknown")
        items_ok = result.get("pages_processed", result.get("notes_processed", 0))
        items_failed = sum(
            1 for r in result.get("results", []) if r.get("status") == "error"
        )
        self.db.log_sync(
            webhook_id=webhook_id,
            status=status,
            items_processed=items_ok - items_failed,
            items_failed=items_failed,
            details=result,
        )

        return result

    # ── Content extraction ────────────────────────────────────────────────────

    def _extract_content(self, payload: Dict, source_config: Dict) -> str:
        """Extract a text string from an inbound webhook payload."""
        source_type = source_config.get("type")

        if source_type == "obsidian":
            from utils.obsidian_handler import process_obsidian_webhook
            return process_obsidian_webhook(payload)

        if "page_id" in payload:
            from utils.notion_handler import fetch_notion_page
            return fetch_notion_page(payload["page_id"])

        if "content" in payload:
            return payload["content"]
        elif "text" in payload:
            return payload["text"]
        else:
            import json
            return json.dumps(payload, indent=2)

    # ── Source sync methods ───────────────────────────────────────────────────

    def _sync_notion(self, webhook: Dict) -> Dict:
        """Fetch all pages from a Notion database and upload to destination."""
        from utils.notion_handler import fetch_notion_database

        source = webhook["source"]
        database_id = source.get("database_id")
        if not database_id:
            raise ValueError("Notion database_id required")

        pages = fetch_notion_database(database_id)
        destination = webhook["destination"]
        platform = destination.get("platform", "openai")
        adapter = PlatformFactory.create(platform, destination)

        results = []
        for page in pages:
            try:
                result = adapter.upload(
                    content=page["content"].encode("utf-8"),
                    filename=f"{page['title']}.txt",
                    content_type="text/plain",
                    metadata={
                        "webhook_id": webhook["id"],
                        "notion_page_id": page["id"],
                        "synced_at": datetime.utcnow().isoformat(),
                        "source": "notion",
                    },
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync Notion page {page['id']}: {e}")
                results.append({"status": "error", "page_id": page["id"], "error": str(e)})

        return {
            "status": "synced",
            "pages_processed": len(results),
            "results": results,
        }

    def _sync_obsidian(self, webhook: Dict) -> Dict:
        """Fetch all notes from an Obsidian vault and upload to destination."""
        from utils.obsidian_handler import fetch_obsidian_vault

        source = webhook["source"]
        vault_name = source.get("vault_name", "")

        try:
            notes = fetch_obsidian_vault(vault_name)
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "note": "Obsidian sync requires the Local REST API plugin to be running",
            }

        destination = webhook["destination"]
        platform = destination.get("platform", "openai")
        adapter = PlatformFactory.create(platform, destination)

        results = []
        for note in notes:
            try:
                result = adapter.upload(
                    content=note["content"].encode("utf-8"),
                    filename=f"{note['title']}.md",
                    content_type="text/markdown",
                    metadata={
                        "webhook_id": webhook["id"],
                        "obsidian_path": note["id"],
                        "synced_at": datetime.utcnow().isoformat(),
                        "source": "obsidian",
                    },
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync Obsidian note {note['id']}: {e}")
                results.append({"status": "error", "note_id": note["id"], "error": str(e)})

        return {
            "status": "synced",
            "notes_processed": len(results),
            "results": results,
        }

    def _sync_github(self, webhook: Dict) -> Dict:
        """Sync from a GitHub repository — not yet implemented."""
        raise NotImplementedError("GitHub sync is not yet implemented")

    # ── Background polling ────────────────────────────────────────────────────

    def start(self):
        """Start background polling threads for all webhooks with poll_interval set."""
        if self.running:
            return
        self.running = True
        webhooks = self.db.get_all_webhooks()
        for webhook_id, webhook in webhooks.items():
            if webhook.get("enabled") and webhook.get("source", {}).get("poll_interval"):
                self._start_poll_thread(webhook_id)
        logger.info(f"WebhookGenerator started ({len(self.threads)} polling threads)")

    def _start_poll_thread(self, webhook_id: str):
        """Spawn a daemon polling thread for a single webhook."""
        thread = threading.Thread(
            target=self._poll_webhook,
            args=(webhook_id,),
            daemon=True,
        )
        thread.start()
        self.threads.append(thread)
        logger.info(f"Started polling thread for webhook {webhook_id}")

    def _poll_webhook(self, webhook_id: str):
        """Poll a webhook source repeatedly at its configured interval."""
        while self.running:
            try:
                webhook = self.db.get_webhook(webhook_id)
                if not webhook or not webhook.get("enabled"):
                    break

                interval = webhook.get("source", {}).get("poll_interval", 300)
                self.trigger_webhook(webhook_id)
                time.sleep(interval)

            except Exception as e:
                logger.error(f"Polling error for webhook {webhook_id}: {e}")
                time.sleep(60)  # Back off 1 minute before retrying

    def stop(self):
        """Signal all polling threads to stop and wait for them to finish."""
        self.running = False
        for thread in self.threads:
            thread.join(timeout=5)
        logger.info("All webhook polling threads stopped")
