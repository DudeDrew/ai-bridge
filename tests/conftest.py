"""
Shared pytest fixtures for AI Bridge tests.
Environment variables are set here, before any app module is imported.
"""
import os
import pytest
from unittest.mock import MagicMock, patch

# ── Test environment variables ────────────────────────────────────────────────
# Must be set before any module-level import triggers os.getenv().
os.environ.setdefault("BRIDGE_API_KEY", "test-api-key-123")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test_ai_bridge")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-openai-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("PINECONE_API_KEY", "test-pinecone-key")
os.environ.setdefault("NOTION_TOKEN", "secret_test_notion_token")
os.environ.setdefault("OBSIDIAN_API_KEY", "test-obsidian-key")
os.environ.setdefault("OBSIDIAN_API_URL", "http://localhost:27123")


# ── Shared mock fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """A MagicMock that satisfies the DBManager interface."""
    db = MagicMock()
    db.get_webhook.return_value = None
    db.get_all_webhooks.return_value = {}
    db.get_recent_sync_log.return_value = []
    db.get_sync_log.return_value = []
    db.get_dedup.return_value = None
    return db


@pytest.fixture
def mock_generator():
    """A MagicMock that satisfies the WebhookGenerator interface."""
    gen = MagicMock()
    gen.process_incoming_webhook.return_value = {"status": "success"}
    gen.trigger_webhook.return_value = {
        "status": "synced", "pages_processed": 3, "results": []
    }
    gen.create_webhook.return_value = "test1234"
    return gen


# ── Flask app fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def app(mock_db, mock_generator):
    """
    Flask test app with DB and generator replaced by mocks.
    Resets module-level singletons before each test so tests are isolated.
    """
    import main as m

    # Reset lazy singletons so each test starts from a clean state
    m._db = None
    m._generator = None
    m._started = False

    m.app.config["TESTING"] = True
    m.app.config["SECRET_KEY"] = "test-secret-key"

    with patch("main.get_db", return_value=mock_db), \
         patch("main.get_generator", return_value=mock_generator):
        yield m.app


@pytest.fixture
def client(app):
    """Unauthenticated test client."""
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """Test client with an active dashboard session."""
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["authenticated"] = True
        yield c


# ── Sample data fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def notion_openai_config():
    """A valid Notion → OpenAI webhook config."""
    return {
        "name": "Test Notion → OpenAI",
        "source": {"type": "notion", "database_id": "abc123def456"},
        "destination": {"platform": "openai", "vector_store_id": "vs_test123"},
        "enabled": True,
    }


@pytest.fixture
def sample_webhook(notion_openai_config):
    """A saved webhook with id and timestamps."""
    return {
        **notion_openai_config,
        "id": "ab12cd34",
        "created_at": "2026-02-24T00:00:00",
    }
