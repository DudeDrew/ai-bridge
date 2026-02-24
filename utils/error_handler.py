# --------------------------
# utils/error_handler.py
# --------------------------
import logging
from functools import wraps
from flask import jsonify

logger = logging.getLogger(__name__)


def error_response(message: str, status_code: int = 500, details: dict = None):
    """Build a standardized JSON error response tuple."""
    body = {"error": message, "status_code": status_code}
    if details:
        body["details"] = details
    return jsonify(body), status_code


def handle_exceptions(f):
    """
    Route decorator that catches unhandled exceptions and returns a
    standardized JSON error response instead of a 500 HTML page.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.warning(f"Validation error in {f.__name__}: {e}")
            return error_response(str(e), 400)
        except PermissionError as e:
            logger.warning(f"Permission error in {f.__name__}: {e}")
            return error_response(str(e), 403)
        except KeyError as e:
            logger.warning(f"Missing key in {f.__name__}: {e}")
            return error_response(f"Missing required field: {e}", 400)
        except NotImplementedError as e:
            logger.warning(f"Not implemented in {f.__name__}: {e}")
            return error_response(str(e), 501)
        except Exception as e:
            logger.error(f"Unhandled error in {f.__name__}: {e}", exc_info=True)
            return error_response("Internal server error", 500)
    return decorated


# Map of exception types to HTTP status codes
EXCEPTION_STATUS_MAP = {
    ValueError: 400,
    KeyError: 400,
    PermissionError: 403,
    FileNotFoundError: 404,
    NotImplementedError: 501,
}


def exception_to_status(e: Exception) -> int:
    """Return the appropriate HTTP status code for a given exception."""
    for exc_type, status in EXCEPTION_STATUS_MAP.items():
        if isinstance(e, exc_type):
            return status
    return 500
