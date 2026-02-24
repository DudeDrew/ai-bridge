# --------------------------
# main.py
# --------------------------
import logging
import os
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("BRIDGE_API_KEY", "dev-secret-change-me")

# ── App-level singletons ──────────────────────────────────────────────────────
# Initialized lazily on first request so gunicorn workers don't all race at startup.

_db = None
_generator = None
_started = False


def get_db():
    global _db
    if _db is None:
        from utils.db_manager import DBManager
        _db = DBManager()
    return _db


def get_generator():
    global _generator
    if _generator is None:
        from utils.webhook_generator import WebhookGenerator
        _generator = WebhookGenerator(get_db())
    return _generator


@app.before_request
def _start_background():
    """Start polling threads on the first request (once per worker process)."""
    global _started
    if not _started:
        _started = True
        try:
            get_generator().start()
            logger.info("Background polling engine started")
        except Exception as e:
            logger.error(f"Failed to start background engine: {e}")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _valid_api_key(provided: str) -> bool:
    from utils.validator import validate_api_key
    expected = os.getenv("BRIDGE_API_KEY", "")
    if not expected:
        return False
    return validate_api_key(provided, expected)


def require_api_key(f):
    """Protect JSON API routes with an X-API-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key", "")
        if not _valid_api_key(key):
            return jsonify({"error": "Invalid or missing API key", "status_code": 401}), 401
        return f(*args, **kwargs)
    return decorated


def require_session(f):
    """Protect dashboard HTML routes via session cookie."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


# ── Auth pages ────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        provided = request.form.get("api_key", "").strip()
        if _valid_api_key(provided):
            session["authenticated"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        error = "Incorrect API key. Check your BRIDGE_API_KEY environment variable."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Dashboard routes (HTML) ───────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@require_session
def dashboard():
    try:
        db = get_db()
        webhooks = db.get_all_webhooks()
        recent_log = db.get_recent_sync_log(limit=10)
    except Exception as e:
        logger.error(f"Dashboard data load failed: {e}")
        webhooks = {}
        recent_log = []
    base_url = request.host_url.rstrip("/")
    return render_template(
        "index.html",
        webhooks=webhooks,
        recent_log=recent_log,
        base_url=base_url,
    )


@app.route("/dashboard/connections/new", methods=["GET", "POST"])
@require_session
def new_connection():
    error = None
    if request.method == "POST":
        # Accept JSON (from Alpine.js fetch) or form-encoded
        data = request.get_json(silent=True)
        if data is None:
            data = request.form.to_dict(flat=True)

        try:
            config = _build_config_from_post(data)
            from utils.validator import validate_webhook_config
            validate_webhook_config(config)
            webhook_id = get_generator().create_webhook(config)
            # JSON response for Alpine.js to handle redirect
            if request.is_json:
                webhook = get_db().get_webhook(webhook_id)
                webhook["webhook_url"] = f"{request.host_url}webhook/{webhook_id}"
                return jsonify({"status": "created", "webhook": webhook}), 201
            return redirect(url_for("dashboard"))
        except ValueError as e:
            error = str(e)
            if request.is_json:
                return jsonify({"error": error}), 400
        except Exception as e:
            logger.error(f"Create webhook failed: {e}")
            error = "An unexpected error occurred. Please try again."
            if request.is_json:
                return jsonify({"error": error}), 500

    return render_template("new_connection.html", error=error)


@app.route("/dashboard/connections/<webhook_id>/delete", methods=["POST"])
@require_session
def delete_connection(webhook_id):
    try:
        get_generator().delete_webhook(webhook_id)
    except Exception as e:
        logger.error(f"Delete webhook {webhook_id} failed: {e}")
    return redirect(url_for("dashboard"))


@app.route("/dashboard/connections/<webhook_id>/trigger", methods=["POST"])
@require_session
def trigger_connection(webhook_id):
    try:
        result = get_generator().trigger_webhook(webhook_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except NotImplementedError as e:
        return jsonify({"error": str(e)}), 501
    except Exception as e:
        logger.error(f"Trigger webhook {webhook_id} failed: {e}")
        return jsonify({"error": "Sync failed. Check logs for details."}), 500


@app.route("/dashboard/connections/<webhook_id>/toggle", methods=["POST"])
@require_session
def toggle_connection(webhook_id):
    try:
        db = get_db()
        webhook = db.get_webhook(webhook_id)
        if not webhook:
            return jsonify({"error": "Not found"}), 404
        webhook["enabled"] = not webhook.get("enabled", True)
        db.save_webhook(webhook_id, webhook)
        return jsonify({"enabled": webhook["enabled"]})
    except Exception as e:
        logger.error(f"Toggle webhook {webhook_id} failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/dashboard/connections/<webhook_id>/history")
@require_session
def connection_history(webhook_id):
    db = get_db()
    webhook = db.get_webhook(webhook_id)
    if not webhook:
        return redirect(url_for("dashboard"))
    log = db.get_sync_log(webhook_id, limit=100)
    base_url = request.host_url.rstrip("/")
    return render_template("history.html", webhook=webhook, log=log, base_url=base_url)


# ── REST API routes (JSON) ────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "service": "ai-bridge",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@app.route("/webhook/<webhook_id>", methods=["POST"])
def inbound_webhook(webhook_id):
    """Receive an inbound webhook push from Notion, Obsidian, or any source."""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        result = get_generator().process_incoming_webhook(webhook_id, payload)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Inbound webhook {webhook_id} error: {e}")
        return jsonify({"error": "Processing failed"}), 500


@app.route("/api/webhooks", methods=["GET"])
@require_api_key
def api_list_webhooks():
    return jsonify(get_db().get_all_webhooks())


@app.route("/api/webhooks", methods=["POST"])
@require_api_key
def api_create_webhook():
    config = request.get_json()
    if not config:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        from utils.validator import validate_webhook_config
        validate_webhook_config(config)
        webhook_id = get_generator().create_webhook(config)
        webhook = get_db().get_webhook(webhook_id)
        webhook["webhook_url"] = f"{request.host_url}webhook/{webhook_id}"
        return jsonify(webhook), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"API create webhook failed: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/webhooks/<webhook_id>", methods=["DELETE"])
@require_api_key
def api_delete_webhook(webhook_id):
    if not get_db().get_webhook(webhook_id):
        return jsonify({"error": f"Webhook {webhook_id} not found"}), 404
    get_generator().delete_webhook(webhook_id)
    return jsonify({"status": "deleted", "webhook_id": webhook_id})


@app.route("/api/webhooks/<webhook_id>/trigger", methods=["POST"])
@require_api_key
def api_trigger_webhook(webhook_id):
    try:
        return jsonify(get_generator().trigger_webhook(webhook_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except NotImplementedError as e:
        return jsonify({"error": str(e)}), 501
    except Exception as e:
        logger.error(f"API trigger {webhook_id} failed: {e}")
        return jsonify({"error": "Sync failed"}), 500


@app.route("/api/webhooks/<webhook_id>/log", methods=["GET"])
@require_api_key
def api_webhook_log(webhook_id):
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify(get_db().get_sync_log(webhook_id, limit=limit))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_config_from_post(data: dict) -> dict:
    """
    Assemble a webhook config dict from flat POST fields.
    Handles both Alpine.js JSON payloads and regular form submissions.
    """
    # Alpine.js sends a nested JSON object directly
    if "source" in data and isinstance(data["source"], dict):
        return data

    # Regular form fields use dot-notation names (e.g. source.type)
    config = {
        "name": data.get("name", "").strip() or None,
        "source": {
            "type": data.get("source_type", ""),
            "database_id": data.get("source_database_id", "").strip() or None,
            "vault_name": data.get("source_vault_name", "").strip() or None,
        },
        "destination": {
            "platform": data.get("destination_platform", ""),
            "vector_store_id": data.get("destination_vector_store_id", "").strip() or None,
            "index_name": data.get("destination_index_name", "").strip() or None,
            "namespace": data.get("destination_namespace", "").strip() or None,
        },
        "enabled": True,
    }

    poll_raw = data.get("source_poll_interval", "").strip()
    if poll_raw.isdigit():
        config["source"]["poll_interval"] = int(poll_raw)

    # Remove None values from nested dicts to keep configs clean
    config["source"] = {k: v for k, v in config["source"].items() if v is not None}
    config["destination"] = {k: v for k, v in config["destination"].items() if v is not None}

    return config


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
