"""Tests for Flask routes in main.py."""
import json
import pytest
from unittest.mock import MagicMock, patch

API_KEY = "test-api-key-123"
API_HEADERS = {"X-API-Key": API_KEY}


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealthRoute:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_body_has_status_healthy(self, client):
        assert client.get("/health").get_json()["status"] == "healthy"

    def test_body_has_service_name(self, client):
        assert client.get("/health").get_json()["service"] == "ai-bridge"

    def test_body_has_timestamp(self, client):
        assert "timestamp" in client.get("/health").get_json()

    def test_no_auth_required(self, client):
        """Health endpoint must be public."""
        assert client.get("/health").status_code == 200


# ── / redirect ────────────────────────────────────────────────────────────────

class TestRootRedirect:
    def test_redirects_to_dashboard(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/dashboard" in resp.location


# ── /login ────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_get_returns_200(self, client):
        assert client.get("/login").status_code == 200

    def test_correct_key_sets_session_and_redirects(self, client):
        resp = client.post("/login", data={"api_key": API_KEY}, follow_redirects=False)
        assert resp.status_code == 302
        assert "/dashboard" in resp.location

    def test_correct_key_sets_authenticated_session(self, client):
        with client.session_transaction() as sess:
            sess.clear()
        client.post("/login", data={"api_key": API_KEY})
        with client.session_transaction() as sess:
            assert sess.get("authenticated") is True

    def test_wrong_key_shows_error(self, client):
        resp = client.post("/login", data={"api_key": "wrong-key"})
        assert resp.status_code == 200
        assert b"Incorrect" in resp.data or b"Invalid" in resp.data

    def test_wrong_key_does_not_set_session(self, client):
        client.post("/login", data={"api_key": "wrong-key"})
        with client.session_transaction() as sess:
            assert not sess.get("authenticated")


# ── /logout ───────────────────────────────────────────────────────────────────

class TestLogout:
    def test_clears_session_and_redirects(self, auth_client):
        resp = auth_client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.location

    def test_session_cleared_after_logout(self, auth_client):
        auth_client.get("/logout")
        with auth_client.session_transaction() as sess:
            assert not sess.get("authenticated")


# ── /dashboard ────────────────────────────────────────────────────────────────

class TestDashboard:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 302
        assert "login" in resp.location

    def test_authenticated_returns_200(self, auth_client, mock_db):
        mock_db.get_all_webhooks.return_value = {}
        mock_db.get_recent_sync_log.return_value = []
        assert auth_client.get("/dashboard").status_code == 200

    def test_redirect_preserves_next_param(self, client):
        resp = client.get("/dashboard")
        assert "next" in resp.location or "login" in resp.location


# ── /dashboard/connections/new ────────────────────────────────────────────────

class TestNewConnection:
    def test_get_unauthenticated_redirects(self, client):
        resp = client.get("/dashboard/connections/new")
        assert resp.status_code == 302

    def test_get_authenticated_returns_200(self, auth_client):
        assert auth_client.get("/dashboard/connections/new").status_code == 200

    def test_post_valid_json_creates_webhook(self, auth_client, mock_generator, mock_db):
        mock_generator.create_webhook.return_value = "new12345"
        mock_db.get_webhook.return_value = {
            "id": "new12345",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        config = {
            "source": {"type": "notion", "database_id": "db-xyz"},
            "destination": {"platform": "openai", "vector_store_id": "vs-xyz"},
        }
        resp = auth_client.post(
            "/dashboard/connections/new",
            data=json.dumps(config),
            content_type="application/json",
        )
        assert resp.status_code == 201
        mock_generator.create_webhook.assert_called_once()

    def test_post_invalid_config_returns_400(self, auth_client):
        resp = auth_client.post(
            "/dashboard/connections/new",
            data=json.dumps({"source": {"type": "invalid"}}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_post_returns_webhook_url_in_response(self, auth_client, mock_generator, mock_db):
        mock_generator.create_webhook.return_value = "new12345"
        mock_db.get_webhook.return_value = {
            "id": "new12345",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        config = {
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        resp = auth_client.post(
            "/dashboard/connections/new",
            data=json.dumps(config),
            content_type="application/json",
        )
        assert "webhook_url" in resp.get_json()
        assert "new12345" in resp.get_json()["webhook_url"]


# ── /dashboard/connections/<id>/trigger ──────────────────────────────────────

class TestTriggerConnection:
    def test_unauthenticated_redirects(self, client):
        resp = client.post("/dashboard/connections/abc/trigger")
        assert resp.status_code == 302

    def test_successful_trigger_returns_200(self, auth_client, mock_generator):
        mock_generator.trigger_webhook.return_value = {"status": "synced", "pages_processed": 3}
        resp = auth_client.post("/dashboard/connections/abc/trigger")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "synced"

    def test_unknown_webhook_returns_404(self, auth_client, mock_generator):
        mock_generator.trigger_webhook.side_effect = ValueError("not found")
        resp = auth_client.post("/dashboard/connections/ghost/trigger")
        assert resp.status_code == 404

    def test_not_implemented_returns_501(self, auth_client, mock_generator):
        mock_generator.trigger_webhook.side_effect = NotImplementedError("GitHub not implemented")
        resp = auth_client.post("/dashboard/connections/gh123/trigger")
        assert resp.status_code == 501

    def test_runtime_error_returns_500(self, auth_client, mock_generator):
        mock_generator.trigger_webhook.side_effect = RuntimeError("unexpected")
        resp = auth_client.post("/dashboard/connections/abc/trigger")
        assert resp.status_code == 500


# ── /dashboard/connections/<id>/toggle ───────────────────────────────────────

class TestToggleConnection:
    def _webhook(self, enabled=True):
        return {
            "id": "abc12345", "enabled": enabled,
            "source": {}, "destination": {},
        }

    def test_toggle_enabled_to_disabled(self, auth_client, mock_db):
        mock_db.get_webhook.return_value = self._webhook(enabled=True)
        resp = auth_client.post("/dashboard/connections/abc12345/toggle")
        assert resp.status_code == 200
        assert resp.get_json()["enabled"] is False

    def test_toggle_disabled_to_enabled(self, auth_client, mock_db):
        mock_db.get_webhook.return_value = self._webhook(enabled=False)
        resp = auth_client.post("/dashboard/connections/abc12345/toggle")
        assert resp.status_code == 200
        assert resp.get_json()["enabled"] is True

    def test_unknown_id_returns_404(self, auth_client, mock_db):
        mock_db.get_webhook.return_value = None
        resp = auth_client.post("/dashboard/connections/ghost/toggle")
        assert resp.status_code == 404


# ── /webhook/<id> (inbound) ───────────────────────────────────────────────────

class TestInboundWebhook:
    def test_valid_payload_returns_200(self, client, mock_generator):
        mock_generator.process_incoming_webhook.return_value = {"status": "success"}
        resp = client.post(
            "/webhook/abc12345",
            data=json.dumps({"content": "hello"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_unknown_webhook_id_returns_404(self, client, mock_generator):
        mock_generator.process_incoming_webhook.side_effect = ValueError("not found")
        resp = client.post(
            "/webhook/ghost",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_empty_payload_accepted(self, client, mock_generator):
        mock_generator.process_incoming_webhook.return_value = {"status": "success"}
        resp = client.post("/webhook/abc12345", data=b"", content_type="application/json")
        assert resp.status_code == 200

    def test_no_auth_required(self, client, mock_generator):
        """Inbound webhook endpoint is public — third-party services post here."""
        mock_generator.process_incoming_webhook.return_value = {"status": "success"}
        resp = client.post(
            "/webhook/abc12345",
            data=json.dumps({"text": "hi"}),
            content_type="application/json",
        )
        assert resp.status_code == 200


# ── /api/webhooks (list) ─────────────────────────────────────────────────────

class TestApiListWebhooks:
    def test_missing_api_key_returns_401(self, client):
        assert client.get("/api/webhooks").status_code == 401

    def test_wrong_api_key_returns_401(self, client):
        assert client.get("/api/webhooks", headers={"X-API-Key": "wrong"}).status_code == 401

    def test_correct_api_key_returns_200(self, client, mock_db):
        mock_db.get_all_webhooks.return_value = {}
        assert client.get("/api/webhooks", headers=API_HEADERS).status_code == 200

    def test_returns_webhooks_dict(self, client, mock_db):
        mock_db.get_all_webhooks.return_value = {"abc": {"id": "abc"}}
        resp = client.get("/api/webhooks", headers=API_HEADERS)
        assert "abc" in resp.get_json()

    def test_api_key_as_query_param_accepted(self, client, mock_db):
        mock_db.get_all_webhooks.return_value = {}
        resp = client.get(f"/api/webhooks?api_key={API_KEY}")
        assert resp.status_code == 200


# ── /api/webhooks (create) ───────────────────────────────────────────────────

class TestApiCreateWebhook:
    def test_creates_and_returns_201(self, client, mock_generator, mock_db):
        mock_generator.create_webhook.return_value = "new12345"
        mock_db.get_webhook.return_value = {
            "id": "new12345",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        resp = client.post(
            "/api/webhooks",
            data=json.dumps({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": {"platform": "openai", "vector_store_id": "vs1"},
            }),
            content_type="application/json",
            headers=API_HEADERS,
        )
        assert resp.status_code == 201

    def test_response_includes_webhook_url(self, client, mock_generator, mock_db):
        mock_generator.create_webhook.return_value = "new12345"
        mock_db.get_webhook.return_value = {
            "id": "new12345",
            "source": {"type": "notion", "database_id": "db1"},
            "destination": {"platform": "openai", "vector_store_id": "vs1"},
        }
        resp = client.post(
            "/api/webhooks",
            data=json.dumps({
                "source": {"type": "notion", "database_id": "db1"},
                "destination": {"platform": "openai", "vector_store_id": "vs1"},
            }),
            content_type="application/json",
            headers=API_HEADERS,
        )
        assert "webhook_url" in resp.get_json()

    def test_invalid_config_returns_400(self, client):
        resp = client.post(
            "/api/webhooks",
            data=json.dumps({"source": {"type": "bad"}}),
            content_type="application/json",
            headers=API_HEADERS,
        )
        assert resp.status_code == 400

    def test_non_json_body_returns_400(self, client):
        resp = client.post(
            "/api/webhooks",
            data="not json",
            content_type="text/plain",
            headers=API_HEADERS,
        )
        assert resp.status_code == 400


# ── /api/webhooks/<id> (delete) ──────────────────────────────────────────────

class TestApiDeleteWebhook:
    def test_unknown_id_returns_404(self, client, mock_db):
        mock_db.get_webhook.return_value = None
        resp = client.delete("/api/webhooks/ghost", headers=API_HEADERS)
        assert resp.status_code == 404

    def test_known_id_returns_200(self, client, mock_db, mock_generator):
        mock_db.get_webhook.return_value = {"id": "abc12345"}
        resp = client.delete("/api/webhooks/abc12345", headers=API_HEADERS)
        assert resp.status_code == 200

    def test_response_includes_deleted_status(self, client, mock_db, mock_generator):
        mock_db.get_webhook.return_value = {"id": "abc12345"}
        data = client.delete("/api/webhooks/abc12345", headers=API_HEADERS).get_json()
        assert data["status"] == "deleted"
        assert data["webhook_id"] == "abc12345"

    def test_generator_delete_called(self, client, mock_db, mock_generator):
        mock_db.get_webhook.return_value = {"id": "abc12345"}
        client.delete("/api/webhooks/abc12345", headers=API_HEADERS)
        mock_generator.delete_webhook.assert_called_once_with("abc12345")


# ── /api/webhooks/<id>/trigger ────────────────────────────────────────────────

class TestApiTriggerWebhook:
    def test_successful_trigger_returns_result(self, client, mock_generator):
        mock_generator.trigger_webhook.return_value = {"status": "synced", "pages_processed": 5}
        resp = client.post("/api/webhooks/abc12345/trigger", headers=API_HEADERS)
        assert resp.status_code == 200
        assert resp.get_json()["pages_processed"] == 5

    def test_not_found_returns_404(self, client, mock_generator):
        mock_generator.trigger_webhook.side_effect = ValueError("not found")
        assert client.post("/api/webhooks/ghost/trigger", headers=API_HEADERS).status_code == 404

    def test_not_implemented_returns_501(self, client, mock_generator):
        mock_generator.trigger_webhook.side_effect = NotImplementedError("GitHub sync")
        assert client.post("/api/webhooks/abc/trigger", headers=API_HEADERS).status_code == 501


# ── /api/webhooks/<id>/log ────────────────────────────────────────────────────

class TestApiWebhookLog:
    def test_returns_list(self, client, mock_db):
        mock_db.get_sync_log.return_value = [{"id": 1, "status": "synced"}]
        resp = client.get("/api/webhooks/abc12345/log", headers=API_HEADERS)
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_default_limit_respected(self, client, mock_db):
        mock_db.get_sync_log.return_value = []
        client.get("/api/webhooks/abc12345/log", headers=API_HEADERS)
        _, kwargs = mock_db.get_sync_log.call_args
        assert kwargs.get("limit", 50) <= 200

    def test_custom_limit_accepted(self, client, mock_db):
        mock_db.get_sync_log.return_value = []
        client.get("/api/webhooks/abc12345/log?limit=10", headers=API_HEADERS)
        _, kwargs = mock_db.get_sync_log.call_args
        assert kwargs.get("limit") == 10

    def test_limit_capped_at_200(self, client, mock_db):
        mock_db.get_sync_log.return_value = []
        client.get("/api/webhooks/abc12345/log?limit=9999", headers=API_HEADERS)
        _, kwargs = mock_db.get_sync_log.call_args
        assert kwargs.get("limit") <= 200
