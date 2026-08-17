"""An identifier from a request must never reach outside its own directory.

`DELETE /api/graph/project/%2e%2e` and `DELETE /api/report/%2e%2e` used to empty
the whole uploads tree: Werkzeug does not normalise a lone `..` segment, so
os.path.join put the manager on the parent directory and shutil.rmtree finished
the job. Reproduced four ways, including under gunicorn with the Dockerfile's
command line.

Everything here runs against a sandbox under tmp_path. Nothing touches the real
uploads directory.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.config import Config
from app.models.project import ProjectManager
from app.utils.resource_ids import UnsafeResourceId, safe_child_path, validate_resource_id


class SimulationOn(Config):
    """The routes under test belong to the simulation lane, off by default.

    Without pinning the flag these tests would still pass, and mean nothing: an
    unregistered `/api/...` DELETE answers 405, because the SPA catch-all only
    accepts GET, and 405 satisfies `>= 400` exactly as well as a real rejection
    does. The traversal guard would be untested and nobody would notice.
    """

    MIROFISH_ENABLE_SIMULATION = True


ESCAPES = [
    "..",
    ".",
    "../..",
    "..%2f..",
    "....//..",
    "/etc",
    "a/b",
    "a\\b",
    ".hidden",
    "",
]


@pytest.mark.parametrize("value", ESCAPES)
def test_escaping_identifiers_are_rejected(value):
    with pytest.raises(UnsafeResourceId):
        validate_resource_id(value, kind="project_id")


@pytest.mark.parametrize(
    "value",
    ["proj_0123456789ab", "report_abcdef012345", "sim-1", "A_b-9", "x" * 128],
)
def test_real_identifiers_still_pass(value):
    """Deliberately not pinned to the generated format.

    Pinning `proj_<12 hex>` would reject older identifiers already sitting in an
    operator's uploads directory, turning a security fix into data loss.
    """
    assert validate_resource_id(value, kind="project_id") == value


def test_safe_child_path_keeps_the_result_under_the_base(tmp_path):
    child = safe_child_path(str(tmp_path), "proj_0123456789ab", kind="project_id")
    assert child.startswith(str(tmp_path))


def test_project_dir_helper_refuses_to_climb_out(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    with pytest.raises(UnsafeResourceId):
        ProjectManager._get_project_dir("..")


def test_delete_project_endpoint_leaves_the_uploads_tree_intact(tmp_path, monkeypatch):
    """The exploit, end to end. Red before the fix, green after."""
    uploads = tmp_path / "uploads"
    projects = uploads / "projects"
    projects.mkdir(parents=True)
    (projects / "proj_0123456789ab").mkdir()
    (projects / "proj_0123456789ab" / "project.json").write_text("{}")
    canary = uploads / "reports"
    canary.mkdir()
    (canary / "keep.md").write_text("survive")

    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects))
    app = create_app(SimulationOn)
    assert "graph" in app.blueprints, "route must exist for this test to mean anything"
    client = app.test_client()

    response = client.delete("/api/graph/project/%2e%2e")

    # Exactly 400, not merely "an error": 405 would mean the route vanished and
    # 500 would mean the guard threw instead of refusing.
    assert response.status_code == 400
    # The whole point: everything is still on disk.
    assert (projects / "proj_0123456789ab" / "project.json").exists()
    assert (canary / "keep.md").read_text() == "survive"
    assert sorted(p.name for p in uploads.iterdir()) == ["projects", "reports"]


def test_delete_report_endpoint_leaves_the_uploads_tree_intact(tmp_path, monkeypatch):
    """The second reachable route, and the one that also leaked its path.

    ReportManager.delete_report reached the same rmtree, and the JSON error body
    echoed the absolute directory back to the caller.
    """
    from app.services.report_agent import ReportManager

    uploads = tmp_path / "uploads"
    reports = uploads / "reports"
    reports.mkdir(parents=True)
    (reports / "report_0123456789ab").mkdir()
    (reports / "keep.md").write_text("survive")
    (uploads / "projects").mkdir()

    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))
    app = create_app(SimulationOn)
    assert "report" in app.blueprints, "route must exist for this test to mean anything"
    client = app.test_client()

    response = client.delete("/api/report/%2e%2e")

    # This route catches Exception itself, so it re-raises UnsafeResourceId to
    # let the app-level handler answer 400 rather than reporting a server fault.
    assert response.status_code == 400
    assert (reports / "keep.md").read_text() == "survive"
    assert (reports / "report_0123456789ab").exists()
    assert sorted(p.name for p in uploads.iterdir()) == ["projects", "reports"]
    # The rejection must not hand the caller a filesystem path.
    assert str(tmp_path) not in response.get_data(as_text=True)


def test_delete_project_endpoint_still_reports_a_missing_project(tmp_path, monkeypatch):
    """Validation must not turn every lookup into an error."""
    projects = tmp_path / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(projects))
    client = create_app(SimulationOn).test_client()

    response = client.delete("/api/graph/project/proj_0123456789ab")

    # Not widened to include 405: that would hide the route disappearing, which
    # is the exact failure this file exists to catch.
    assert response.status_code in (200, 404)
