# --------------------------
# adapters/pinecone_adapter.py
# --------------------------
import hashlib
import os
from typing import Dict, Any, List

from openai import OpenAI
from pinecone import Pinecone

from .base_adapter import BasePlatformAdapter

# Chunking constants
_CHUNK_SIZE = 1500    # characters per chunk
_CHUNK_OVERLAP = 150  # overlap to preserve context across chunk boundaries


class PineconeAdapter(BasePlatformAdapter):
    """
    Pinecone vector database adapter.

    Splits text into overlapping chunks, generates embeddings via OpenAI,
    and upserts them to a Pinecone index. Requires both PINECONE_API_KEY
    and OPENAI_API_KEY (for embeddings) to be configured.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        pinecone_api_key = config.get("api_key") or os.getenv("PINECONE_API_KEY")
        if not pinecone_api_key:
            raise ValueError("Pinecone API key is required (set PINECONE_API_KEY)")

        self.pc = Pinecone(api_key=pinecone_api_key)
        self.index_name = config.get("index_name")
        if not self.index_name:
            raise ValueError("'index_name' is required in Pinecone destination config")

        self.namespace = config.get("namespace", "")
        self.embedding_model = config.get("embedding_model", "text-embedding-3-small")

        openai_api_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
        self._embed_client = OpenAI(api_key=openai_api_key)

    # ── Public interface ──────────────────────────────────────────────────────

    def upload(self, content: bytes, filename: str, content_type: str, metadata: Dict) -> Dict:
        """
        Chunk text, embed each chunk, and upsert vectors to Pinecone.

        Vectors are keyed as '<content_hash>_<chunk_index>' so re-uploading
        the same content is idempotent (Pinecone upsert overwrites on conflict).
        """
        try:
            text = content.decode("utf-8", errors="replace")
            chunks = self._chunk_text(text)

            if not chunks:
                return {"status": "skipped", "reason": "empty content", "platform": "pinecone"}

            # Stable base ID derived from filename + first 256 chars of content
            base_id = hashlib.sha256((filename + text[:256]).encode()).hexdigest()[:16]

            embeddings = self._embed(chunks)

            vectors = [
                {
                    "id": f"{base_id}_{i}",
                    "values": emb,
                    "metadata": {
                        **{k: str(v) for k, v in metadata.items()},  # Pinecone requires str values
                        "filename": filename,
                        "chunk_index": i,
                        "chunk_count": len(chunks),
                        "text": chunk[:1000],  # Pinecone metadata value size limit
                    },
                }
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ]

            index = self.pc.Index(self.index_name)
            # Upsert in batches of 100 (Pinecone recommendation)
            for start in range(0, len(vectors), 100):
                index.upsert(vectors=vectors[start : start + 100], namespace=self.namespace)

            self.logger.info(
                f"Upserted {len(vectors)} vectors to Pinecone '{self.index_name}' for '{filename}'"
            )
            return {
                "status": "success",
                "vectors_upserted": len(vectors),
                "index": self.index_name,
                "namespace": self.namespace,
                "platform": "pinecone",
            }

        except Exception as e:
            self.logger.error(f"Pinecone upload failed: {e}")
            raise

    def fetch(self, resource_id: str) -> bytes:
        """Fetch a vector's stored text metadata by vector ID."""
        try:
            index = self.pc.Index(self.index_name)
            result = index.fetch(ids=[resource_id], namespace=self.namespace)
            vectors = result.get("vectors", {})
            if resource_id in vectors:
                text = vectors[resource_id].get("metadata", {}).get("text", "")
                return text.encode("utf-8")
            return b""
        except Exception as e:
            self.logger.error(f"Pinecone fetch failed for {resource_id}: {e}")
            raise

    def delete(self, resource_id: str) -> bool:
        """Delete a vector by ID."""
        try:
            index = self.pc.Index(self.index_name)
            index.delete(ids=[resource_id], namespace=self.namespace)
            return True
        except Exception as e:
            self.logger.error(f"Pinecone delete failed for {resource_id}: {e}")
            return False

    def list_resources(self) -> list:
        """Return index statistics (Pinecone doesn't support listing all vector IDs)."""
        try:
            index = self.pc.Index(self.index_name)
            stats = index.describe_index_stats()
            return [{"index": self.index_name, "stats": dict(stats)}]
        except Exception as e:
            self.logger.error(f"Pinecone list_resources failed: {e}")
            return []

    def validate_config(self) -> bool:
        """Verify the index exists and is reachable."""
        if not self.index_name:
            return False
        try:
            self.pc.Index(self.index_name).describe_index_stats()
            return True
        except Exception:
            return False

    def health_check(self) -> Dict:
        """Check connectivity to the Pinecone index."""
        try:
            self.pc.Index(self.index_name).describe_index_stats()
            return {"status": "healthy", "platform": "pinecone", "index": self.index_name}
        except Exception as e:
            return {"status": "unhealthy", "platform": "pinecone", "error": str(e)}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping fixed-size character chunks."""
        text = text.strip()
        if not text:
            return []

        chunks = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_SIZE
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - _CHUNK_OVERLAP

        return chunks

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of text strings using OpenAI."""
        response = self._embed_client.embeddings.create(
            model=self.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]
