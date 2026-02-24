# --------------------------
# adapters/anthropic_adapter.py
# --------------------------
import io
import os
from typing import Dict, Any

import anthropic

from .base_adapter import BasePlatformAdapter


class AnthropicAdapter(BasePlatformAdapter):
    """
    Anthropic Files API adapter.

    Uploads content as files that can be referenced in Claude messages.
    Requires anthropic>=0.40.0 for beta Files API support.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        api_key = config.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Anthropic API key is required (set ANTHROPIC_API_KEY)")
        self.client = anthropic.Anthropic(api_key=api_key)

    def upload(self, content: bytes, filename: str, content_type: str, metadata: Dict) -> Dict:
        """
        Upload a file to the Anthropic Files API.

        The returned file_id can be used in subsequent Claude API calls to
        reference this content without re-uploading.
        """
        try:
            # Check for duplicates using DB-backed dedup
            dedup_key = self.get_dedup_key(content, filename)
            cached_id = self._check_dedup(dedup_key)
            if cached_id:
                self.logger.info(f"Duplicate detected: {filename}, skipping upload")
                return {
                    "status": "skipped",
                    "reason": "duplicate",
                    "file_id": cached_id,
                    "platform": "anthropic",
                }

            response = self.client.beta.files.upload(
                file=(filename, io.BytesIO(content), content_type),
            )

            self._store_dedup(dedup_key, response.id)
            self.logger.info(f"Uploaded file to Anthropic Files API: {response.id} ({filename})")

            return {
                "status": "success",
                "file_id": response.id,
                "filename": filename,
                "platform": "anthropic",
            }

        except anthropic.APIError as e:
            self.logger.error(f"Anthropic API error during upload: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            raise

    def fetch(self, resource_id: str) -> bytes:
        """Download the raw content of a previously uploaded file."""
        try:
            response = self.client.beta.files.download(resource_id)
            return response.read()
        except Exception as e:
            self.logger.error(f"Fetch failed for {resource_id}: {e}")
            raise

    def delete(self, resource_id: str) -> bool:
        """Delete a file from the Anthropic Files API."""
        try:
            self.client.beta.files.delete(resource_id)
            return True
        except Exception as e:
            self.logger.error(f"Delete failed for {resource_id}: {e}")
            return False

    def list_resources(self) -> list:
        """List all files stored in the Anthropic Files API."""
        try:
            response = self.client.beta.files.list()
            return [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "created_at": str(f.created_at),
                    "size": getattr(f, "size", None),
                }
                for f in response.data
            ]
        except Exception as e:
            self.logger.error(f"list_resources failed: {e}")
            return []

    def validate_config(self) -> bool:
        """Verify the API key is valid by listing files."""
        try:
            self.client.beta.files.list()
            return True
        except Exception:
            return False

    def health_check(self) -> Dict:
        """Check connectivity to the Anthropic Files API."""
        try:
            self.client.beta.files.list()
            return {"status": "healthy", "platform": "anthropic"}
        except Exception as e:
            return {"status": "unhealthy", "platform": "anthropic", "error": str(e)}

    # ── Dedup helpers (DB-backed via db_manager module) ───────────────────────

    def _check_dedup(self, dedup_key: str) -> str | None:
        """Return cached file_id if this content was already uploaded, else None."""
        try:
            from utils.db_manager import DBManager
            db = DBManager()
            return db.get_dedup(dedup_key, "anthropic")
        except Exception:
            return None

    def _store_dedup(self, dedup_key: str, file_id: str) -> None:
        """Cache a successful upload for deduplication."""
        try:
            from utils.db_manager import DBManager
            db = DBManager()
            db.set_dedup(dedup_key, file_id, "anthropic")
        except Exception as e:
            self.logger.warning(f"Could not store dedup entry: {e}")
