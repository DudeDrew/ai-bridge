# --------------------------
# utils/db_manager.py
# --------------------------
import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[ThreadedConnectionPool] = None

_CREATE_WEBHOOKS = """
CREATE TABLE IF NOT EXISTS webhooks (
    id          VARCHAR(8) PRIMARY KEY,
    config      JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

_CREATE_SYNC_LOG = """
CREATE TABLE IF NOT EXISTS sync_log (
    id               SERIAL PRIMARY KEY,
    webhook_id       VARCHAR(8) REFERENCES webhooks(id) ON DELETE CASCADE,
    synced_at        TIMESTAMPTZ DEFAULT NOW(),
    status           VARCHAR(20) NOT NULL,
    items_processed  INTEGER DEFAULT 0,
    items_failed     INTEGER DEFAULT 0,
    details          JSONB
);
"""

_CREATE_DEDUP = """
CREATE TABLE IF NOT EXISTS dedup_cache (
    dedup_key   TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    platform    TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
"""


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable is not set")
        _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=database_url)
        logger.info("Database connection pool initialized")
    return _pool


class DBManager:
    """PostgreSQL CRUD layer for webhooks, sync logs, and dedup cache."""

    def __init__(self):
        self._init_schema()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self):
        """Create tables if they don't exist."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(_CREATE_WEBHOOKS)
                cur.execute(_CREATE_SYNC_LOG)
                cur.execute(_CREATE_DEDUP)
            conn.commit()
            logger.info("Database schema initialized")
        except Exception as e:
            conn.rollback()
            logger.error(f"Schema init failed: {e}")
            raise
        finally:
            pool.putconn(conn)

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def get_webhook(self, webhook_id: str) -> Optional[Dict]:
        """Return webhook config dict, or None if not found."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT config FROM webhooks WHERE id = %s", (webhook_id,))
                row = cur.fetchone()
                return dict(row["config"]) if row else None
        finally:
            pool.putconn(conn)

    def save_webhook(self, webhook_id: str, config: Dict) -> None:
        """Insert or update a webhook config (upsert)."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO webhooks (id, config, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE
                        SET config = EXCLUDED.config, updated_at = NOW()
                    """,
                    (webhook_id, json.dumps(config)),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"save_webhook failed: {e}")
            raise
        finally:
            pool.putconn(conn)

    def delete_webhook(self, webhook_id: str) -> None:
        """Delete a webhook and its associated sync logs (cascade)."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM webhooks WHERE id = %s", (webhook_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"delete_webhook failed: {e}")
            raise
        finally:
            pool.putconn(conn)

    def get_all_webhooks(self) -> Dict[str, Dict]:
        """Return all webhooks as {webhook_id: config_dict}, newest first."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, config FROM webhooks ORDER BY created_at DESC")
                return {row["id"]: dict(row["config"]) for row in cur.fetchall()}
        finally:
            pool.putconn(conn)

    # ── Sync Log ──────────────────────────────────────────────────────────────

    def log_sync(
        self,
        webhook_id: str,
        status: str,
        items_processed: int = 0,
        items_failed: int = 0,
        details: Optional[Dict] = None,
    ) -> None:
        """Append a sync event to the log."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sync_log
                        (webhook_id, status, items_processed, items_failed, details)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (webhook_id, status, items_processed, items_failed, json.dumps(details or {})),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"log_sync failed: {e}")
        finally:
            pool.putconn(conn)

    def get_sync_log(self, webhook_id: str, limit: int = 50) -> list:
        """Return the most recent sync events for a specific webhook."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, synced_at, status, items_processed, items_failed, details
                    FROM sync_log
                    WHERE webhook_id = %s
                    ORDER BY synced_at DESC
                    LIMIT %s
                    """,
                    (webhook_id, limit),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            pool.putconn(conn)

    def get_recent_sync_log(self, limit: int = 20) -> list:
        """Return the most recent sync events across all webhooks."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT sl.id, sl.webhook_id, sl.synced_at, sl.status,
                           sl.items_processed, sl.items_failed, sl.details
                    FROM sync_log sl
                    ORDER BY sl.synced_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            pool.putconn(conn)

    # ── Dedup Cache ───────────────────────────────────────────────────────────

    def get_dedup(self, dedup_key: str, platform: str) -> Optional[str]:
        """Return cached resource_id for a dedup key, or None if not cached."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT resource_id FROM dedup_cache WHERE dedup_key = %s AND platform = %s",
                    (dedup_key, platform),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            pool.putconn(conn)

    def set_dedup(self, dedup_key: str, resource_id: str, platform: str) -> None:
        """Store or update a dedup entry."""
        pool = _get_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dedup_cache (dedup_key, resource_id, platform)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (dedup_key) DO UPDATE SET resource_id = EXCLUDED.resource_id
                    """,
                    (dedup_key, resource_id, platform),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"set_dedup failed: {e}")
        finally:
            pool.putconn(conn)
