# CLAUDE.md — AI Bridge

This file provides context and conventions for AI assistants (Claude, etc.) working in this repository.

## Project Overview

**Universal AI Bridge** is a platform-agnostic webhook bridge that routes content from knowledge bases (Notion, Obsidian) to AI platforms (OpenAI, Anthropic/Claude, Pinecone). It exposes a Flask web application with a dashboard UI and webhook endpoints, deployed on Render.com.

**Core use case**: A user triggers a sync (via webhook or polling), the bridge fetches content from a source (Notion DB, Obsidian vault), and uploads it to a destination AI platform (e.g., OpenAI vector store, Claude knowledge base, Pinecone index).

---

## Repository Structure

```
ai-bridge/
├── main.py                    # Flask app entry point (stub — needs implementation)
├── requirements.txt           # Python dependencies (stub — needs packages)
├── render.yaml                # Render.com deployment config (complete)
├── .env.example               # Environment variable template (stub)
├── .gitignore                 # Git ignore rules (stub)
├── README.md                  # User-facing documentation
│
├── adapters/                  # Platform-specific destination adapters
│   ├── __init__.py            # Package init (stub)
│   ├── base_adapter.py        # Abstract base class for all adapters (stub)
│   ├── platform_factory.py    # Factory to instantiate adapters by name (stub)
│   ├── openai_adapter.py      # OpenAI vector store adapter (COMPLETE)
│   ├── anthropic_adapter.py   # Anthropic/Claude adapter (stub)
│   ├── pinecone_adapter.py    # Pinecone vector DB adapter (stub)
│   └── SETUP_FILES.MD         # Adapter setup notes (stub)
│
└── utils/                     # Shared utilities
    ├── __init__.py            # Package init (stub)
    ├── db_manager.py          # PostgreSQL database manager (stub)
    ├── error_handler.py       # Centralized error handling (stub)
    ├── notion_handler.py      # Notion API integration (stub)
    ├── obsidian_handler.py    # Obsidian Local REST API integration (stub)
    ├── validator.py           # Input validation helpers (stub)
    └── webhook_generator.py   # Webhook CRUD + polling engine (COMPLETE, has issues)
```

### Implementation Status

| File | Status | Notes |
|------|--------|-------|
| `main.py` | Stub | Flask app, routes, auth middleware all missing |
| `requirements.txt` | Stub | No packages listed yet |
| `.env.example` | Stub | No env var docs yet |
| `adapters/base_adapter.py` | Stub | Abstract base class not written |
| `adapters/platform_factory.py` | Stub | Factory pattern not implemented |
| `adapters/openai_adapter.py` | **Complete** | Full OpenAI vector store upload/fetch/delete |
| `adapters/anthropic_adapter.py` | Stub | |
| `adapters/pinecone_adapter.py` | Stub | |
| `utils/db_manager.py` | Stub | PostgreSQL CRUD for routes/webhooks |
| `utils/error_handler.py` | Stub | |
| `utils/notion_handler.py` | Stub | `fetch_notion_page`, `fetch_notion_database` expected |
| `utils/obsidian_handler.py` | Stub | `fetch_obsidian_vault`, `process_obsidian_webhook` expected |
| `utils/validator.py` | Stub | |
| `utils/webhook_generator.py` | **Mostly complete** | See known issues below |

---

## Architecture

### Adapter Pattern

All destination platforms implement the `BasePlatformAdapter` interface (to be defined in `adapters/base_adapter.py`). The `PlatformFactory` creates the correct adapter at runtime based on a string key.

Expected interface (based on `openai_adapter.py`):

```python
class BasePlatformAdapter:
    def upload(self, content: bytes, filename: str, content_type: str, metadata: Dict) -> Dict: ...
    def fetch(self, resource_id: str) -> bytes: ...
    def delete(self, resource_id: str) -> bool: ...
    def list_resources(self) -> list: ...
    def validate_config(self) -> bool: ...
    def health_check(self) -> Dict: ...
    def get_dedup_key(self, content: bytes, filename: str) -> str: ...  # for deduplication
```

### Data Flow

```
Source (Notion/Obsidian) → webhook trigger or polling
    → WebhookGenerator._extract_content() or _sync_*()
    → PlatformFactory.create(platform, config)
    → adapter.upload(content, filename, content_type, metadata)
    → Destination (OpenAI/Claude/Pinecone)
```

### Database

Uses PostgreSQL (via Render's managed database). The `db_manager.py` is expected to implement:
- `get_webhook(webhook_id)` → Dict
- `save_webhook(webhook_id, config)` → None
- `delete_webhook(webhook_id)` → None
- `get_all_webhooks()` → Dict[str, Dict]

Connection string is provided via the `DATABASE_URL` environment variable.

---

## Environment Variables

Defined in `render.yaml`; document in `.env.example` when implementing:

| Variable | Source | Purpose |
|----------|--------|---------|
| `BRIDGE_API_KEY` | Auto-generated by Render | Dashboard authentication |
| `DATABASE_URL` | Render PostgreSQL | DB connection string |
| `OPENAI_API_KEY` | Manual (secrets) | OpenAI API access |
| `ANTHROPIC_API_KEY` | Manual (secrets) | Anthropic/Claude API access |
| `NOTION_TOKEN` | Manual (secrets) | Notion integration token |
| `OBSIDIAN_API_KEY` | Manual (secrets) | Obsidian Local REST API key |
| `OBSIDIAN_API_URL` | Manual | Obsidian Local REST API base URL |
| `FLASK_ENV` | `production` | Flask environment |

---

## Deployment

The app is deployed to **Render.com** using `render.yaml`.

- **Build command**: `pip install -r requirements.txt`
- **Start command**: `gunicorn main:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
- **Plan**: Free tier (web service sleeps after 15 min inactivity)
- **Region**: Oregon
- **Database**: Free Render PostgreSQL (`ai-bridge-db`, database `ai_bridge`, user `bridge_user`)

The Flask app object **must** be exposed as `app` in `main.py` for gunicorn to find it.

---

## Known Issues & Incomplete Areas

### `webhook_generator.py` — Duplicate method + ordering bug

`trigger_webhook` is defined **twice** in `WebhookGenerator` (lines 74 and 152). The first definition at line 74 includes Obsidian support but appears before `__init__`. The second at line 152 is the canonical definition but lacks Obsidian. When implementing, merge them and place `__init__` first.

The correct merged `trigger_webhook` should support: `notion`, `obsidian`, `github`.

### `_sync_github` — Not implemented

`_sync_github` raises `NotImplementedError`. Do not call it until implemented.

### Deduplication — In-memory only

`openai_adapter.py` uses a dict (`self.dedup_cache`) for deduplication. This is instance-local and lost on restart. The TODO comment says "In production, use Redis." When persisting state matters, replace with Redis or DB-backed deduplication.

### `main.py` is empty

The Flask application, all routes, authentication middleware, and the web dashboard are not yet implemented. This is the primary missing piece before the app can run.

### `requirements.txt` is empty

No dependencies are listed. Based on the code, the following packages are required at minimum:

```
flask
gunicorn
openai
anthropic
pinecone-client
psycopg2-binary
requests
notion-client
```

---

## Coding Conventions

### Python Style

- **Python 3.x** (exact version unspecified; target 3.10+ for modern typing)
- Type hints on all function signatures (`Dict`, `Any`, `str`, `bytes`, etc. from `typing`)
- Docstrings on all public methods (single-line description format used in `openai_adapter.py`)
- Module-level logger: `logger = logging.getLogger(__name__)`

### Adapter Conventions

- Each adapter lives in its own file: `adapters/<platform>_adapter.py`
- Class name pattern: `<Platform>Adapter` (e.g., `OpenAIAdapter`, `AnthropicAdapter`)
- Constructor takes `config: Dict[str, Any]`, calls `super().__init__(config)`
- API key falls back to environment variable if not in config:
  ```python
  api_key = config.get('api_key') or os.getenv('OPENAI_API_KEY')
  ```
- All methods wrap exceptions and re-raise or return error dicts; never swallow silently
- Return dicts from `upload()` always include a `"status"` key

### Webhook / Source Handler Conventions

- Source handlers live in `utils/<source>_handler.py`
- Free functions (not classes), imported lazily inside methods to avoid circular imports
- Notion handler must expose: `fetch_notion_page(page_id)`, `fetch_notion_database(database_id)`
- Obsidian handler must expose: `fetch_obsidian_vault(vault_name)`, `process_obsidian_webhook(payload)`

### Error Handling

- Use `logger.error(f"...: {e}")` before re-raising or returning error dicts
- `upload()` and similar I/O methods should `raise` on failure (caller handles)
- `delete()` should return `bool` — `True` on success, `False` on failure (log the error)

### Webhook IDs

Generated as the first 8 characters of a UUID4:
```python
webhook_id = str(uuid.uuid4())[:8]
```

### Timestamps

Always use UTC:
```python
datetime.utcnow().isoformat()
```

---

## Development Workflow

### Local Setup (once requirements.txt and main.py exist)

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and configure environment
cp .env.example .env
# Edit .env with your API keys

# 4. Run the app
flask run
# or
python main.py
```

### Testing

No test framework is configured yet. When adding tests:
- Use `pytest`
- Place tests in a `tests/` directory
- Mirror the source structure: `tests/adapters/`, `tests/utils/`

### Git Branches

- Default branch for feature development: `claude/add-claude-documentation-tfV83`
- Main/production branch: `main`
- Always push to the feature branch; open a PR to merge to `main`

---

## What to Implement Next

Priority order for making the app functional:

1. **`requirements.txt`** — Add all dependencies
2. **`main.py`** — Flask app with routes: `GET /`, `POST /webhook/<id>`, `GET /health`, etc.
3. **`utils/db_manager.py`** — PostgreSQL CRUD layer
4. **`adapters/base_adapter.py`** — Abstract base class
5. **`adapters/platform_factory.py`** — Factory: `PlatformFactory.create(platform, config)`
6. **`.env.example`** — Document all env vars
7. **`utils/notion_handler.py`** — Notion API calls
8. **`utils/obsidian_handler.py`** — Obsidian Local REST API calls
9. **`adapters/anthropic_adapter.py`** — Claude knowledge base upload
10. **`adapters/pinecone_adapter.py`** — Pinecone upsert
11. **Fix `webhook_generator.py`** — Merge duplicate `trigger_webhook`, ensure `__init__` is first
