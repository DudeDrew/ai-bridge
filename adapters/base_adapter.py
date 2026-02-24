# --------------------------
# adapters/base_adapter.py
# --------------------------
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any


class BasePlatformAdapter(ABC):
    """Abstract base class for all platform destination adapters."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def upload(self, content: bytes, filename: str, content_type: str, metadata: Dict) -> Dict:
        """Upload content to the platform. Returns dict with at least a 'status' key."""
        ...

    @abstractmethod
    def fetch(self, resource_id: str) -> bytes:
        """Fetch raw content of a previously uploaded resource."""
        ...

    @abstractmethod
    def delete(self, resource_id: str) -> bool:
        """Delete a resource. Returns True on success, False on failure."""
        ...

    @abstractmethod
    def list_resources(self) -> list:
        """List all resources managed by this adapter."""
        ...

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate that the adapter configuration is correct and reachable."""
        ...

    @abstractmethod
    def health_check(self) -> Dict:
        """Return a health status dict with at least 'status' and 'platform' keys."""
        ...

    def get_dedup_key(self, content: bytes, filename: str) -> str:
        """Generate a deduplication key based on a SHA-256 content hash and filename."""
        content_hash = hashlib.sha256(content).hexdigest()[:16]
        return f"{filename}:{content_hash}"
