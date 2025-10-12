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
    Manages webhook generation and polling
    Monitors sources and pushes updates to destinations
    """
    

    def _sync_obsidian(self, webhook: Dict) -> Dict:
        """Sync from Obsidian vault"""
        from utils.obsidian_handler import fetch_obsidian_vault
        
        source = webhook["source"]
        vault_name = source.get("vault_name", "")
        
        # Fetch all notes from vault
        try:
            notes = fetch_obsidian_vault(vault_name)
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "note": "Obsidian sync requires Local REST API plugin"
            }
        
        # Upload each note
        destination = webhook["destination"]
        platform = destination.get("platform", "openai")
        adapter = PlatformFactory.create(platform, destination)
        
        results = []
        for note in notes:
            try:
                result = adapter.upload(
                    content=note["content"].encode('utf-8'),
                    filename=f"{note['title']}.md",
                    content_type="text/markdown",
                    metadata={
                        "webhook_id": webhook["id"],
                        "obsidian_path": note["id"],
                        "synced_at": datetime.utcnow().isoformat(),
                        "source": "obsidian"
                    }
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync note {note['id']}: {e}")
                results.append({
                    "status": "error",
                    "note_id": note["id"],
                    "error": str(e)
                })
        
        return {
            "status": "synced",
            "notes_processed": len(results),
            "results": results
        }

# Also update the trigger_webhook method to handle obsidian:
    def trigger_webhook(self, webhook_id: str) -> Dict:
        """Manually trigger webhook (poll source and sync)"""
        webhook = self.db.get_webhook(webhook_id)
        
        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")
        
        source = webhook.get("source", {})
        source_type = source.get("type")
        
        if source_type == "notion":
            return self._sync_notion(webhook)
        elif source_type == "obsidian":
            return self._sync_obsidian(webhook)
        elif source_type == "github":
            return self._sync_github(webhook)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
        
    def __init__(self, db_manager):
        self.db = db_manager
        self.running = False
        self.threads = []
    
    def create_webhook(self, config: Dict[str, Any]) -> str:
        """Create new webhook configuration"""
        webhook_id = str(uuid.uuid4())[:8]
        
        webhook_config = {
            **config,
            "id": webhook_id,
            "created_at": datetime.utcnow().isoformat(),
            "enabled": config.get("enabled", True)
        }
        
        self.db.save_webhook(webhook_id, webhook_config)
        logger.info(f"Created webhook: {webhook_id}")
        
        return webhook_id
    
    def delete_webhook(self, webhook_id: str):
        """Delete webhook"""
        self.db.delete_webhook(webhook_id)
        logger.info(f"Deleted webhook: {webhook_id}")
    
    def process_incoming_webhook(self, webhook_id: str, payload: Dict) -> Dict:
        """Process incoming webhook data"""
        webhook = self.db.get_webhook(webhook_id)
        
        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")
        
        if not webhook.get("enabled", True):
            return {"status": "disabled"}
        
        # Extract content from payload
        content = self._extract_content(payload, webhook.get("source", {}))
        
        # Upload to destination
        destination = webhook.get("destination", {})
        platform = destination.get("platform", "openai")
        
        adapter = PlatformFactory.create(platform, destination)
        
        result = adapter.upload(
            content=content.encode('utf-8'),
            filename=f"webhook_{webhook_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt",
            content_type="text/plain",
            metadata={
                "webhook_id": webhook_id,
                "received_at": datetime.utcnow().isoformat(),
                "source": webhook.get("source", {}).get("type", "unknown")
            }
        )
        
        logger.info(f"Processed webhook {webhook_id}: {result}")
        return result
    
    def trigger_webhook(self, webhook_id: str) -> Dict:
        """Manually trigger webhook (poll source and sync)"""
        webhook = self.db.get_webhook(webhook_id)
        
        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")
        
        source = webhook.get("source", {})
        source_type = source.get("type")
        
        if source_type == "notion":
            return self._sync_notion(webhook)
        elif source_type == "github":
            return self._sync_github(webhook)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")
    
    # Update this method in WebhookGenerator class

    def _extract_content(self, payload: Dict, source_config: Dict) -> str:
        """Extract content from webhook payload"""
        source_type = source_config.get("type")
        
        # Handle Obsidian payloads
        if source_type == "obsidian":
            from utils.obsidian_handler import process_obsidian_webhook
            return process_obsidian_webhook(payload)
        
        # Handle Notion payloads
        if "page_id" in payload:
            from utils.notion_handler import fetch_notion_page
            return fetch_notion_page(payload["page_id"])
        
        # Generic content extraction
        if "content" in payload:
            return payload["content"]
        elif "text" in payload:
            return payload["text"]
        else:
            import json
            return json.dumps(payload, indent=2)
    
    def _sync_notion(self, webhook: Dict) -> Dict:
        """Sync from Notion database"""
        from utils.notion_handler import fetch_notion_database
        
        source = webhook["source"]
        database_id = source.get("database_id")
        
        if not database_id:
            raise ValueError("Notion database_id required")
        
        # Fetch all pages from database
        pages = fetch_notion_database(database_id)
        
        # Upload each page
        destination = webhook["destination"]
        platform = destination.get("platform", "openai")
        adapter = PlatformFactory.create(platform, destination)
        
        results = []
        for page in pages:
            try:
                result = adapter.upload(
                    content=page["content"].encode('utf-8'),
                    filename=f"{page['title']}.txt",
                    content_type="text/plain",
                    metadata={
                        "webhook_id": webhook["id"],
                        "notion_page_id": page["id"],
                        "synced_at": datetime.utcnow().isoformat()
                    }
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync page {page['id']}: {e}")
                results.append({"status": "error", "page_id": page["id"], "error": str(e)})
        
        return {"status": "synced", "pages_processed": len(results), "results": results}
    
    def _sync_github(self, webhook: Dict) -> Dict:
        """Sync from GitHub repository"""
        # Implementation for GitHub sync
        raise NotImplementedError("GitHub sync not yet implemented")
    
    def start(self):
        """Start background polling threads"""
        if self.running:
            return
        
        self.running = True
        
        # Start polling thread for each webhook with polling enabled
        webhooks = self.db.get_all_webhooks()
        
        for webhook_id, webhook in webhooks.items():
            if webhook.get("enabled") and webhook.get("source", {}).get("poll_interval"):
                thread = threading.Thread(
                    target=self._poll_webhook,
                    args=(webhook_id,),
                    daemon=True
                )
                thread.start()
                self.threads.append(thread)
                logger.info(f"Started polling thread for webhook {webhook_id}")
    
    def _poll_webhook(self, webhook_id: str):
        """Poll webhook source at intervals"""
        while self.running:
            try:
                webhook = self.db.get_webhook(webhook_id)
                
                if not webhook or not webhook.get("enabled"):
                    break
                
                interval = webhook.get("source", {}).get("poll_interval", 300)
                
                # Trigger sync
                self.trigger_webhook(webhook_id)
                
                # Wait for next interval
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Polling error for webhook {webhook_id}: {e}")
                time.sleep(60)  # Wait 1 minute before retrying
    
    def stop(self):
        """Stop all polling threads"""
        self.running = False
        for thread in self.threads:
            thread.join(timeout=5)
        logger.info("All webhook polling threads stopped")