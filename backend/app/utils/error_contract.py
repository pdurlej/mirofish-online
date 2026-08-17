"""One JSON shape for every error that escapes a route.

Two measured problems this addresses.

A storage failure that happens after startup produced Werkzeug's default HTML
error page: `GET /api/audience/runs` returned `text/html` 500 after 139 seconds of
silence, because the audience routes catch only ValueError while graph, report and
simulation wrap their bodies in `except Exception`. A caller parsing JSON gets a
parse error instead of a diagnosis.

And 61 places across `backend/app/api/*.py` return raw `str(e)`, which is how
`DELETE /api/report/..` handed the caller an absolute filesystem path.

Registering handlers does not change any route that already catches its own
exceptions -- those still win. This only shapes what gets through, which today is
the HTML page.
"""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .logger import get_logger
from .resource_ids import UnsafeResourceId


def register_error_handlers(app: Flask) -> None:
    """Install the JSON error contract on an application."""
    logger = get_logger("mirofish.errors")

    @app.errorhandler(UnsafeResourceId)
    def _rejected_identifier(exc: UnsafeResourceId):
        # A malformed identifier is the caller's mistake. Reaching the routes'
        # broad `except Exception` made it a 500, which tells a monitor the
        # server broke when it did not. The message names the field only; the
        # value is attacker-controlled and never echoed.
        return jsonify({"success": False, "error": str(exc)}), 400

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # Keeps 404 and 405 in the same shape as everything else, so a client
        # never has to branch on content type.
        return (
            jsonify({"success": False, "error": exc.name, "status": exc.code}),
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        # Detail goes to the log, not to the caller: exception text here has
        # already been shown to carry absolute paths.
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return (
            jsonify(
                {
                    "success": False,
                    "error": "internal_error",
                    "detail": "The server failed to handle this request.",
                }
            ),
            500,
        )
