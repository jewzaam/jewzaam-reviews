"""Tests for scripts/bootstrap-tmp.sh.

Shared bootstrap invoked by every skill that needs a `.tmp-<skill>/`
workspace. Tested against a temp project root via PROJECT_ROOT.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bootstrap-tmp.sh"


def _has_bash() -> bool:
    return shutil.which("bash") is not None


pytestmark = pytest.mark.skipif(not _has_bash(), reason="bash not available")


def _run(project_root: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(project_root)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestFlatTmpDir:
    def test_first_run_creates_dir_and_gitignore(self, tmp_path: Path):
        result = _run(tmp_path, ".tmp-standards")
        assert result.returncode == 0, result.stderr
        work = tmp_path / ".tmp-standards"
        assert work.is_dir()
        gitignore = work / ".gitignore"
        assert gitignore.is_file()
        assert gitignore.read_text(encoding="utf-8") == "*"

    def test_second_run_is_idempotent(self, tmp_path: Path):
        first = _run(tmp_path, ".tmp-standards")
        assert first.returncode == 0, first.stderr
        second = _run(tmp_path, ".tmp-standards")
        assert second.returncode == 0, second.stderr
        gitignore = tmp_path / ".tmp-standards" / ".gitignore"
        assert gitignore.read_text(encoding="utf-8") == "*"

    def test_wipes_prior_state(self, tmp_path: Path):
        work = tmp_path / ".tmp-standards"
        work.mkdir()
        (work / "stale.json").write_text('{"old": true}', encoding="utf-8")

        result = _run(tmp_path, ".tmp-standards")
        assert result.returncode == 0, result.stderr

        assert not (work / "stale.json").exists()
        assert (work / ".gitignore").read_text(encoding="utf-8") == "*"


class TestSubdirs:
    def test_creates_nested_subdirs(self, tmp_path: Path):
        result = _run(tmp_path, ".tmp-review", "raw", "validation")
        assert result.returncode == 0, result.stderr
        work = tmp_path / ".tmp-review"
        assert (work / "raw").is_dir()
        assert (work / "validation").is_dir()
        assert (work / ".gitignore").read_text(encoding="utf-8") == "*"

    def test_wipes_subdirs(self, tmp_path: Path):
        work = tmp_path / ".tmp-review"
        work.mkdir()
        (work / "raw").mkdir()
        (work / "validation").mkdir()
        (work / "raw" / "stale.json").write_text('{"old": true}', encoding="utf-8")
        (work / "validation" / "batch-1.json").write_text(
            '{"old": true}', encoding="utf-8"
        )
        (work / "consolidated.json").write_text('{"old": true}', encoding="utf-8")

        result = _run(tmp_path, ".tmp-review", "raw", "validation")
        assert result.returncode == 0, result.stderr

        assert not (work / "raw" / "stale.json").exists()
        assert not (work / "validation" / "batch-1.json").exists()
        assert not (work / "consolidated.json").exists()
        assert (work / "raw").is_dir()
        assert (work / "validation").is_dir()


class TestErrors:
    def test_missing_dir_name_arg_exits_nonzero(self, tmp_path: Path):
        result = _run(tmp_path)
        assert result.returncode != 0
        assert "usage:" in result.stderr


class TestInputValidation:
    """The script runs `rm -rf` on the target dir, so any malformed arg must
    be rejected before any filesystem mutation."""

    @pytest.mark.parametrize(
        "bad_dir",
        [
            "..",                   # parent-dir traversal
            "../etc",               # parent traversal with path
            "/etc",                 # absolute path
            "/tmp/stuff",           # absolute
            ".tmp-../escape",       # traversal in the middle
            ".tmp-foo/bar",         # slashes not allowed in dir-name
            ".tmp-",                # empty suffix
            "tmp-foo",              # missing leading dot
            ".tmp-foo bar",         # space
            ".tmp-foo$baz",         # shell metachar
            "",                     # empty string
        ],
    )
    def test_rejects_bad_dir_name(self, tmp_path: Path, bad_dir: str):
        # Pre-seed a real file at the project root to prove nothing gets
        # nuked when the script rejects the input.
        canary = tmp_path / "DO-NOT-DELETE.txt"
        canary.write_text("sentinel", encoding="utf-8")

        result = _run(tmp_path, bad_dir)

        assert result.returncode != 0
        assert canary.exists()
        assert canary.read_text(encoding="utf-8") == "sentinel"

    @pytest.mark.parametrize(
        "bad_subdir",
        [
            "..",
            "../foo",
            "/etc",
            "raw/validation",   # slashes not allowed in single-segment subdir
            ".hidden",          # leading dot not allowed
            "raw bar",          # space
            "raw$x",            # shell metachar
        ],
    )
    def test_rejects_bad_subdir(self, tmp_path: Path, bad_subdir: str):
        canary = tmp_path / "DO-NOT-DELETE.txt"
        canary.write_text("sentinel", encoding="utf-8")

        result = _run(tmp_path, ".tmp-ok", bad_subdir)

        assert result.returncode != 0
        assert canary.exists()
        # The target dir shouldn't have been wiped/created either.
        assert not (tmp_path / ".tmp-ok").exists()
