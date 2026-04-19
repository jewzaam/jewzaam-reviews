"""Tests for scripts/bootstrap-findings-dir.sh.

Invokes the bash script via subprocess against a temp project root, verifies the
.tmp-review-findings/ tree, then runs again to verify idempotence.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bootstrap-findings-dir.sh"


def _has_bash() -> bool:
    return shutil.which("bash") is not None


pytestmark = pytest.mark.skipif(not _has_bash(), reason="bash not available")


def _run(project_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(project_root)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )


class TestBootstrap:
    def test_first_run_creates_tree(self, tmp_path: Path):
        result = _run(tmp_path)
        assert result.returncode == 0, result.stderr
        work = tmp_path / ".tmp-review-findings"
        assert work.is_dir()
        assert (work / "raw").is_dir()
        assert (work / "validation").is_dir()
        gitignore = work / ".gitignore"
        assert gitignore.is_file()
        assert gitignore.read_text(encoding="utf-8") == "*"

    def test_second_run_is_idempotent(self, tmp_path: Path):
        first = _run(tmp_path)
        assert first.returncode == 0, first.stderr
        second = _run(tmp_path)
        assert second.returncode == 0, second.stderr
        gitignore = tmp_path / ".tmp-review-findings" / ".gitignore"
        assert gitignore.read_text(encoding="utf-8") == "*"

    def test_wipes_prior_state(self, tmp_path: Path):
        work = tmp_path / ".tmp-review-findings"
        work.mkdir()
        (work / "raw").mkdir()
        (work / "validation").mkdir()
        (work / "raw" / "stale.json").write_text('{"old": true}', encoding="utf-8")
        (work / "validation" / "batch-1-input.json").write_text(
            '{"old": true}', encoding="utf-8"
        )
        (work / "consolidated.json").write_text('{"old": true}', encoding="utf-8")

        result = _run(tmp_path)
        assert result.returncode == 0, result.stderr

        assert not (work / "raw" / "stale.json").exists()
        assert not (work / "validation" / "batch-1-input.json").exists()
        assert not (work / "consolidated.json").exists()

        assert (work / "raw").is_dir()
        assert (work / "validation").is_dir()
        assert (work / ".gitignore").read_text(encoding="utf-8") == "*"
