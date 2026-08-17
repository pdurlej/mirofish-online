"""Validation for identifiers that become filesystem paths.

`DELETE /api/graph/project/%2e%2e` and `DELETE /api/report/%2e%2e` used to empty
the whole uploads tree. Reproduced four ways, including under gunicorn with the
Dockerfile's exact command line: Werkzeug does not normalise a lone `..` segment,
so `os.path.join(PROJECTS_DIR, '..')` resolved to the parent and `shutil.rmtree`
took everything with it -- project sources, extracted text, reports, simulation
artifacts.

Browsers cannot deliver that payload, since the WHATWG URL parser collapses `..`
and `%2e%2e` before the request leaves. The reachable callers are non-browser
clients: curl, scripts, scanners, anything doing SSRF. That makes it high rather
than critical, and it is still one command.

Two deliberate choices:

* The charset is conservative rather than a pin on the generated format
  (`proj_<12 hex>`, `report_<12 hex>`). Pinning would reject any older
  identifier already sitting in an operator's uploads directory, turning a
  security fix into data loss. Rejecting separators and dots is enough: the
  attack needs one of them.
* Validation lives at the path-building choke points, not in the routes. The
  URL converter refuses `/`, but `project_id` also arrives from request bodies
  and query strings (api/graph.py, api/simulation.py), where nothing filters it.
"""

from __future__ import annotations

import os
import re


# Letters, digits, underscore and hyphen. No separators, no dots, so neither
# ".." nor "." nor "a/b" nor "..%2f.." can survive, whatever the caller encoded.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")


class UnsafeResourceId(ValueError):
    """Raised when an identifier could escape its parent directory."""

    def __init__(self, kind: str, value: str) -> None:
        # The value is deliberately not echoed back: it is attacker-controlled
        # and the API returns error strings to the caller.
        super().__init__(f"invalid {kind}")
        self.kind = kind


def validate_resource_id(value: str | None, *, kind: str = "id") -> str:
    """Return the identifier, or raise if it cannot safely become a path segment."""
    candidate = "" if value is None else str(value)
    if not _SAFE_ID.match(candidate):
        raise UnsafeResourceId(kind, candidate)
    return candidate


def safe_child_path(base_dir: str, value: str | None, *, kind: str = "id") -> str:
    """Join an untrusted identifier onto a base directory, or raise.

    Belt and braces: the identifier is validated, and the resolved path is then
    checked to be inside the base. The second check costs nothing and catches
    anything the charset misses, such as a symlink planted under uploads.
    """
    identifier = validate_resource_id(value, kind=kind)
    candidate = os.path.join(base_dir, identifier)
    resolved = os.path.realpath(candidate)
    root = os.path.realpath(base_dir)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise UnsafeResourceId(kind, identifier)
    return candidate
