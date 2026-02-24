"""Tests for utils/error_handler.py."""
import pytest
from flask import Flask
from utils.error_handler import error_response, handle_exceptions, exception_to_status


@pytest.fixture
def mini_app():
    """Minimal Flask app for testing error handler in a request context."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


# ── error_response ────────────────────────────────────────────────────────────

class TestErrorResponse:
    def test_returns_correct_http_status(self, mini_app):
        with mini_app.app_context():
            _, code = error_response("Bad input", 400)
            assert code == 400

    def test_body_contains_error_message(self, mini_app):
        with mini_app.app_context():
            response, _ = error_response("Something broke", 500)
            data = response.get_json()
            assert data["error"] == "Something broke"

    def test_body_contains_status_code(self, mini_app):
        with mini_app.app_context():
            response, _ = error_response("Not found", 404)
            assert response.get_json()["status_code"] == 404

    def test_details_included_when_provided(self, mini_app):
        with mini_app.app_context():
            response, _ = error_response("Validation failed", 422, details={"field": "source"})
            assert response.get_json()["details"] == {"field": "source"}

    def test_details_key_absent_when_none(self, mini_app):
        with mini_app.app_context():
            response, _ = error_response("Error", 500)
            assert "details" not in response.get_json()

    def test_default_status_is_500(self, mini_app):
        with mini_app.app_context():
            _, code = error_response("Oops")
            assert code == 500

    def test_response_is_json(self, mini_app):
        with mini_app.app_context():
            response, _ = error_response("Error", 400)
            assert response.content_type == "application/json"


# ── handle_exceptions decorator ───────────────────────────────────────────────

class TestHandleExceptions:
    """Each test registers a fresh route that raises a specific exception."""

    def _register(self, app, exc, path="/test"):
        @app.route(path)
        @handle_exceptions
        def _view():
            raise exc
        return app.test_client()

    def test_value_error_returns_400(self, mini_app):
        c = self._register(mini_app, ValueError("bad value"))
        resp = c.get("/test")
        assert resp.status_code == 400
        assert "bad value" in resp.get_json()["error"]

    def test_permission_error_returns_403(self, mini_app):
        c = self._register(mini_app, PermissionError("forbidden"), "/p")
        resp = c.get("/p")
        assert resp.status_code == 403

    def test_key_error_returns_400(self, mini_app):
        c = self._register(mini_app, KeyError("missing_field"), "/k")
        resp = c.get("/k")
        assert resp.status_code == 400

    def test_not_implemented_error_returns_501(self, mini_app):
        c = self._register(mini_app, NotImplementedError("not done"), "/ni")
        resp = c.get("/ni")
        assert resp.status_code == 501

    def test_generic_exception_returns_500(self, mini_app):
        c = self._register(mini_app, RuntimeError("unexpected"), "/rt")
        resp = c.get("/rt")
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "Internal server error"

    def test_successful_route_passes_through(self, mini_app):
        @mini_app.route("/ok")
        @handle_exceptions
        def _ok():
            from flask import jsonify
            return jsonify({"result": "success"})

        resp = mini_app.test_client().get("/ok")
        assert resp.status_code == 200
        assert resp.get_json()["result"] == "success"


# ── exception_to_status ───────────────────────────────────────────────────────

class TestExceptionToStatus:
    def test_value_error_is_400(self):
        assert exception_to_status(ValueError()) == 400

    def test_key_error_is_400(self):
        assert exception_to_status(KeyError()) == 400

    def test_permission_error_is_403(self):
        assert exception_to_status(PermissionError()) == 403

    def test_file_not_found_is_404(self):
        assert exception_to_status(FileNotFoundError()) == 404

    def test_not_implemented_is_501(self):
        assert exception_to_status(NotImplementedError()) == 501

    def test_unknown_exception_is_500(self):
        assert exception_to_status(RuntimeError()) == 500

    def test_subclass_of_value_error_is_400(self):
        class MyError(ValueError):
            pass
        assert exception_to_status(MyError()) == 400
