from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import ruff_changed  # noqa: E402


def test_changed_files_include_branch_worktree_staged_and_untracked(monkeypatch, tmp_path):
    (tmp_path / "branch.py").touch()
    (tmp_path / "worktree.py").touch()
    (tmp_path / "staged.py").touch()
    (tmp_path / "untracked.py").touch()
    (tmp_path / "ignored.txt").touch()
    monkeypatch.setattr(ruff_changed, "ROOT", tmp_path)

    def fake_run(command, **_kwargs):  # noqa: ANN001
        if command[:3] == ["git", "ls-files", "--others"]:
            output = "untracked.py\nignored.txt\n"
        elif command[-1] == "--cached":
            output = "staged.py\n"
        elif "...HEAD" in command[-1]:
            output = "branch.py\n"
        else:
            output = "worktree.py\n"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(ruff_changed.subprocess, "run", fake_run)

    assert ruff_changed.changed_files() == [
        "branch.py",
        "staged.py",
        "untracked.py",
        "worktree.py",
    ]
