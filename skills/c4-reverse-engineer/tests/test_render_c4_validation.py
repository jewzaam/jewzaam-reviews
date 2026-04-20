"""Tests for skills/c4-reverse-engineer/scripts/render-c4-validation.py."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "render-c4-validation.py"
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


class TestRenderC4ValidationJson:
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
        envelope = _load(tmp_path / "Findings-c4-reverse-engineer.json")

        with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(envelope)

        assert envelope["source"] == "c4-validation"
        assert envelope["schema_version"] == _plugin_version()
        assert envelope["issues"] == []

    def test_c4_specific_fields_preserved(self, tmp_path):
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
        envelope = _load(tmp_path / "Findings-c4-reverse-engineer.json")
        for f in envelope["findings"]:
            assert f["verdict"] in {"DISCREPANCY", "MISSING"}
            assert f["artifact"]
            assert f["spec_says"]
            assert f["code_says"]
            assert f["evidence"]

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
        envelope = _load(tmp_path / "Findings-c4-reverse-engineer.json")
        for f in envelope["findings"]:
            assert f["id"][0] in "CIS"
            assert f["id"][1:].isdigit()


class TestRenderC4ValidationMarkdown:
    def test_markdown_includes_summary_and_confirmed(self, tmp_path):
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
        body = (tmp_path / "Findings-c4-reverse-engineer.md").read_text(encoding="utf-8")
        assert "Review: C4 Validation" in body
        assert "## Summary" in body
        assert "l2-c4-container.md" in body
        assert "## Critical" in body
        assert "DISCREPANCY" in body
        assert "## Confirmed" in body
        assert "JWT" in body


class TestValidationFailure:
    def test_bad_verdict_exits_nonzero(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "project": {"name": "x"},
                    "findings": [
                        {
                            "artifact": "l2-c4-container.md",
                            "verdict": "BROKEN",
                            "severity": "critical",
                            "title": "bad verdict",
                            "spec_says": "s",
                            "code_says": "c",
                            "evidence": "e",
                            "locations": [{"path": "p", "line": "1"}],
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
        assert not (tmp_path / "out" / "Findings-c4-reverse-engineer.json").exists()
