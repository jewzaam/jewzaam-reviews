"""Tests for skills/standards/scripts/render-standards.py."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "render-standards.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLUGIN_ROOT = SKILL_ROOT.parent.parent
SHARED_SCHEMA = PLUGIN_ROOT / "schemas" / "findings.schema.json"


def _plugin_version() -> str:
    with (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)["version"]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class TestRenderStandardsJson:
    def test_output_validates_against_shared_schema(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "sample",
            ]
        )
        assert result.returncode == 0, result.stderr
        envelope = _load(tmp_path / "Findings-standards.json")

        with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(envelope)

        assert envelope["source"] == "standards"
        assert envelope["schema_version"] == _plugin_version()
        assert envelope["issues"] == []

    def test_ids_assigned_per_bucket(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "sample",
            ]
        )
        assert result.returncode == 0, result.stderr
        envelope = _load(tmp_path / "Findings-standards.json")

        for f in envelope["findings"]:
            assert f["id"][0] in "CIS"
            assert f["id"][1:].isdigit()
            assert "content_hash" in f
            assert len(f["content_hash"]) == 16

    def test_content_hash_stable(self, tmp_path):
        result1 = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path / "a"),
                "--project-name",
                "sample",
            ]
        )
        result2 = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path / "b"),
                "--project-name",
                "sample",
            ]
        )
        assert result1.returncode == 0
        assert result2.returncode == 0
        a = _load(tmp_path / "a" / "Findings-standards.json")
        b = _load(tmp_path / "b" / "Findings-standards.json")
        assert [f["content_hash"] for f in a["findings"]] == [
            f["content_hash"] for f in b["findings"]
        ]


class TestRenderStandardsMarkdown:
    def test_main_markdown_includes_applicability_and_findings(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "sample",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (tmp_path / "Findings-standards.md").read_text(encoding="utf-8")
        assert "Standards Review: sample" in body
        assert "## Applicability Matrix" in body
        assert "naming.md" in body
        assert "### Critical" in body
        assert "Tests shell out to system python" in body

    def test_supplementary_lists_strengths_and_non_applicable(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "sample",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (
            tmp_path / "Findings-standards-supplementary.md"
        ).read_text(encoding="utf-8")
        assert "## Strengths" in body
        assert "SemVer" in body
        assert "## Non-Applicable Standards" in body
        assert "tkinter/windows.md" in body


class TestRenderStandardsEdgeCases:
    """Covers empty-findings path (I30) and --issues round-trip (I31)."""

    def test_empty_findings_produces_valid_envelope(self, tmp_path):
        pre_render = tmp_path / "empty.json"
        pre_render.write_text(
            json.dumps(
                {
                    "project": {"name": "sample"},
                    "findings": [],
                    "supplementary": {
                        "applicability": [],
                        "strengths": [],
                        "non_applicable": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        result = _run(
            [
                "--input",
                str(pre_render),
                "--out-dir",
                str(tmp_path / "out"),
                "--project-name",
                "sample",
            ]
        )
        assert result.returncode == 0, result.stderr
        envelope = _load(tmp_path / "out" / "Findings-standards.json")
        with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(envelope)
        assert envelope["findings"] == []
        main_md = (tmp_path / "out" / "Findings-standards.md").read_text(
            encoding="utf-8"
        )
        # Empty-bucket branches in the renderer must produce content for a
        # zero-finding audit — otherwise the render path is dead code.
        assert "No critical issues identified" in main_md
        assert "No important issues identified" in main_md
        # Renderer pluralises the suggestion bucket label.
        assert "No suggestions issues identified" in main_md

    def test_issues_round_trip(self, tmp_path):
        issues_path = tmp_path / "issues.json"
        issues_path.write_text(
            json.dumps(
                [
                    {
                        "severity": "warning",
                        "kind": "tool_unavailable",
                        "message": "standards subdomain 'rust' skipped (missing docs)",
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path),
                "--project-name",
                "sample",
                "--issues",
                str(issues_path),
            ]
        )
        assert result.returncode == 0, result.stderr
        envelope = _load(tmp_path / "Findings-standards.json")
        assert len(envelope["issues"]) == 1
        assert envelope["issues"][0]["kind"] == "tool_unavailable"

    def test_malformed_issues_file_fails_cleanly(self, tmp_path):
        # Non-list issues file must fail with a clean error, not a traceback.
        bad_issues = tmp_path / "issues.json"
        bad_issues.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        result = _run(
            [
                "--input",
                str(FIXTURES / "pre-render.sample.json"),
                "--out-dir",
                str(tmp_path / "out"),
                "--project-name",
                "sample",
                "--issues",
                str(bad_issues),
            ]
        )
        assert result.returncode != 0
        # Logging prefixes the level; accept either 'ERROR:' or 'error:' so
        # tests survive a future logging-config tweak.
        assert result.stderr.lower().startswith("error:")


class TestRenderStandardsValidationFailure:
    def test_bad_severity_exits_nonzero(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "project": {"name": "x"},
                    "findings": [
                        {
                            "subdomain": "common",
                            "severity": "blocker",
                            "title": "bad severity",
                            "locations": [{"path": "x", "line": "1"}],
                            "issue": "i",
                            "why_it_matters": "w",
                            "suggested_fix": "f",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = _run(
            [
                "--input",
                str(bad),
                "--out-dir",
                str(tmp_path / "out"),
                "--project-name",
                "x",
            ]
        )
        assert result.returncode != 0
        assert not (tmp_path / "out" / "Findings-standards.json").exists()
