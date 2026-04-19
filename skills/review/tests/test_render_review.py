"""Tests for scripts/render-review.py."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render-review.py"
SCHEMAS = REPO_ROOT / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class TestRenderReviewJson:
    def test_buckets_and_ids_assigned(self, tmp_path):
        out_dir = tmp_path
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),
                "--config",
                str(SCHEMAS / "render-config.default.json"),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr

        json_path = out_dir / "Review-myapp.json"
        assert json_path.exists(), f"expected {json_path} to be created"
        rendered = _load(json_path)

        ids_by_bucket = {
            "critical": [],
            "important": [],
            "suggestion": [],
            "needs-review": [],
        }
        for finding in rendered["findings"]:
            assert "id" in finding
            assert "severity" in finding
            ids_by_bucket[finding["severity"]].append(finding["id"])

        critical = [f for f in rendered["findings"] if f["severity"] == "critical"]
        assert any("SQL injection" in f["title"] for f in critical)

        nr = [f for f in rendered["findings"] if f["severity"] == "needs-review"]
        assert any("Maybe we should log here" in f["title"] for f in nr)

        for bucket, prefix in [
            ("critical", "C"),
            ("important", "I"),
            ("suggestion", "S"),
            ("needs-review", "N"),
        ]:
            ids = ids_by_bucket[bucket]
            for i, fid in enumerate(ids):
                assert (
                    fid == f"{prefix}{i}"
                ), f"bucket {bucket}: expected {prefix}{i}, got {fid}"

    def test_slug_appended_when_provided(self, tmp_path):
        out_dir = tmp_path
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),
                "--config",
                str(SCHEMAS / "render-config.default.json"),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
                "--scope-slug",
                "pr-565",
            ]
        )
        assert result.returncode == 0, result.stderr
        assert (out_dir / "Review-myapp-pr-565.json").exists()


class TestRenderReviewMarkdown:
    def test_main_markdown_lists_critical_findings(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),
                "--config",
                str(SCHEMAS / "render-config.default.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (tmp_path / "Review-myapp.md").read_text(encoding="utf-8")
        assert "# Code Review: myapp" in body
        assert "## Findings" in body
        assert "### Critical" in body
        assert "C0" in body
        assert "SQL injection" in body
        assert "Review-myapp-supplementary.md" in body

    def test_supplementary_lists_decomposition_and_needs_review(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),
                "--config",
                str(SCHEMAS / "render-config.default.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (tmp_path / "Review-myapp-supplementary.md").read_text(encoding="utf-8")
        assert "## Decomposition" in body
        assert "auth subsystem" in body
        assert "## Needs Review" in body
        assert "Maybe we should log here" in body
        assert "## Detailed Analysis" in body
        assert "### Security" in body or "### security" in body.lower()
