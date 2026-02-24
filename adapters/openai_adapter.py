# --------------------------
# adapters/openai_adapter.py
# --------------------------
import io
import os
from typing import Dict, Any
from openai import OpenAI
from .base_adapter import BasePlatformAdapter

class OpenAIAdapter(BasePlatformAdapter):
    """OpenAI Vector Store adapter"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        api_key = config.get('api_key') or os.getenv('OPENAI_API_KEY')
        self.client = OpenAI(api_key=api_key)
        self.vector_store_id = config.get('vector_store_id')
    
    def upload(self, content: bytes, filename: str, content_type: str, metadata: Dict) -> Dict:
        """Upload file to OpenAI vector store"""
        try:
            # Check for duplicates via DB-backed dedup cache
            dedup_key = self.get_dedup_key(content, filename)
            cached_id = self._check_dedup(dedup_key)
            if cached_id:
                self.logger.info(f"Duplicate detected: {filename}, skipping upload")
                return {"status": "skipped", "reason": "duplicate", "file_id": cached_id}
            
            # Step 1: Create file object
            file_obj = self.client.files.create(
                file=io.BytesIO(content),
                purpose="assistants"
            )
            
            self.logger.info(f"Created file object: {file_obj.id}")
            
            # Step 2: Add to vector store
            vector_file = self.client.beta.vector_stores.files.create(
                vector_store_id=self.vector_store_id,
                file_id=file_obj.id
            )
            
            # Persist for deduplication across restarts
            self._store_dedup(dedup_key, file_obj.id)
            
            self.logger.info(f"Added {filename} to vector store {self.vector_store_id}")
            
            return {
                "status": "success",
                "file_id": file_obj.id,
                "vector_file_id": vector_file.id,
                "vector_store_id": self.vector_store_id
            }
        
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            raise
    
    def fetch(self, resource_id: str) -> bytes:
        """Fetch file content"""
        file_content = self.client.files.content(resource_id)
        return file_content.read()
    
    def delete(self, resource_id: str) -> bool:
        """Delete file from vector store"""
        try:
            self.client.beta.vector_stores.files.delete(
                vector_store_id=self.vector_store_id,
                file_id=resource_id
            )
            return True
        except Exception as e:
            self.logger.error(f"Delete failed: {e}")
            return False
    
    def list_resources(self) -> list:
        """List files in vector store"""
        files = self.client.beta.vector_stores.files.list(
            vector_store_id=self.vector_store_id
        )
        return [{"id": f.id, "status": f.status} for f in files.data]
    
    def validate_config(self) -> bool:
        """Validate configuration"""
        if not self.vector_store_id:
            return False
        
        try:
            self.client.beta.vector_stores.retrieve(self.vector_store_id)
            return True
        except:
            return False
    
    def health_check(self) -> Dict:
        """Check OpenAI API status"""
        try:
            self.client.models.list()
            return {"status": "healthy", "platform": "openai"}
        except Exception as e:
            return {"status": "unhealthy", "platform": "openai", "error": str(e)}

    # ── Dedup helpers (DB-backed) ─────────────────────────────────────────────

    def _check_dedup(self, dedup_key: str):
        """Return cached file_id if content was already uploaded, else None."""
        try:
            from utils.db_manager import DBManager
            return DBManager().get_dedup(dedup_key, "openai")
        except Exception:
            return None

    def _store_dedup(self, dedup_key: str, file_id: str) -> None:
        """Persist a dedup entry so future restarts can detect duplicates."""
        try:
            from utils.db_manager import DBManager
            DBManager().set_dedup(dedup_key, file_id, "openai")
        except Exception as e:
            self.logger.warning(f"Could not store dedup entry: {e}")