"""Tests for skills/apply-review/scripts/render-apply-report.py."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "render-apply-report.py"
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


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_happy_path_writes_validated_json(tmp_path):
    pre = tmp_path / "pre.json"
    _write(
        pre,
        {
            "project": {"name": "sample"},
            "applied": [
                {"finding_id": "C0", "outcome": "applied", "detail": "commit 3a7f91c"},
                {"finding_id": "I0", "outcome": "skipped", "detail": "out of scope"},
            ],
            "issues": [
                {
                    "severity": "warning",
                    "kind": "subagent_failure",
                    "message": "test run flaked on S0 once; retried and passed",
                }
            ],
        },
    )

    result = _run(
        [
            "--input",
            str(pre),
            "--out-dir",
            str(tmp_path),
            "--project-name",
            "sample",
        ]
    )
    assert result.returncode == 0, result.stderr

    envelope = _load(tmp_path / "Report-apply-review.json")
    assert envelope["source"] == "apply-review"
    assert envelope["schema_version"] == _plugin_version()
    assert envelope["findings"] == []
    assert len(envelope["applied"]) == 2
    assert len(envelope["issues"]) == 1

    with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator(schema).validate(envelope)


def test_bad_outcome_fails_validation(tmp_path):
    pre = tmp_path / "pre.json"
    _write(
        pre,
        {
            "project": {"name": "sample"},
            "applied": [{"finding_id": "C0", "outcome": "done"}],
        },
    )
    result = _run(
        [
            "--input",
            str(pre),
            "--out-dir",
            str(tmp_path / "out"),
            "--project-name",
            "sample",
        ]
    )
    assert result.returncode != 0
    assert not (tmp_path / "out" / "Report-apply-review.json").exists()


def test_no_markdown_emitted(tmp_path):
    pre = tmp_path / "pre.json"
    _write(pre, {"project": {"name": "sample"}, "applied": []})
    result = _run(
        [
            "--input",
            str(pre),
            "--out-dir",
            str(tmp_path),
            "--project-name",
            "sample",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "Report-apply-review.json").exists()
    md_files = list(tmp_path.glob("Report-apply-review.md"))
    assert md_files == []


class TestValidateInput:
    def test_valid_findings_file_passes(self, tmp_path):
        findings = tmp_path / "Findings-review.json"
        _write(
            findings,
            _load(PLUGIN_ROOT / "schemas" / "examples" / "review.valid.json"),
        )
        result = _run(["--validate-input", str(findings)])
        assert result.returncode == 0, result.stderr
        assert "validates against the shared schema" in result.stdout

    def test_malformed_json_fails(self, tmp_path):
        bad = tmp_path / "Findings-review.json"
        bad.write_text("{ not valid", encoding="utf-8")
        result = _run(["--validate-input", str(bad)])
        assert result.returncode != 0
        assert "not valid JSON" in result.stderr

    def test_schema_violation_fails(self, tmp_path):
        bad = tmp_path / "Findings-review.json"
        doc = _load(PLUGIN_ROOT / "schemas" / "examples" / "review.valid.json")
        doc["source"] = "unknown-source"  # violates the enum
        _write(bad, doc)
        result = _run(["--validate-input", str(bad)])
        assert result.returncode != 0

    def test_missing_file_fails(self, tmp_path):
        result = _run(["--validate-input", str(tmp_path / "does-not-exist.json")])
        assert result.returncode != 0
        assert "not found" in result.stderr
