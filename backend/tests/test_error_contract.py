"""Every error that escapes a route must be JSON, and must not describe the disk.

Measured before this existed: a storage failure after startup returned Werkzeug's
HTML page as `text/html` 500 after 139 seconds, and 61 places in the API return
raw `str(e)` -- which is how a delete handed back an absolute path.

The handlers are tested on a bare Flask app rather than through create_app, so
these assertions are about the contract itself and stay true whichever routes
happen to be registered.
"""

from __future__ import annotations

import pytest
from flask import Flask

from app.utils.error_contract import register_error_handlers
from app.utils.resource_ids import UnsafeResourceId


@pytest.fixture()
def client():
    app = Flask(__name__)
    register_error_handlers(app)

    @app.route("/boom")
    def boom():
        raise RuntimeError("/private/var/secret/path leaked in here")

    @app.route("/bad-id")
    def bad_id():
        raise UnsafeResourceId("report_id", "..")

    return app.test_client()


def test_rejected_identifier_is_a_client_error(client):
    response = client.get("/bad-id")

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json() == {"success": False, "error": "invalid report_id"}


def test_unexpected_error_is_json_and_says_nothing_about_the_disk(client):
    response = client.get("/boom")
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert response.is_json
    assert response.get_json()["error"] == "internal_error"
    # The whole point: neither the path nor the exception text reaches the caller.
    assert "/private/var/secret/path" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body


def test_missing_route_keeps_the_same_shape(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.is_json
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["status"] == 404


def test_wrong_method_keeps_the_same_shape(client):
    response = client.post("/boom")

    assert response.status_code == 405
    assert response.is_json
    assert response.get_json()["status"] == 405
