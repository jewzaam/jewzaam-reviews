"""Tests for skills/update-pr/scripts/render-update-pr.py."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "render-update-pr.py"
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


def test_phase1_json_validates(tmp_path):
    result = _run(
        [
            "--input",
            str(FIXTURES / "pre-render.phase1.sample.json"),
            "--out-dir",
            str(tmp_path),
            "--pr-number",
            "1234",
        ]
    )
    assert result.returncode == 0, result.stderr
    envelope = _load(tmp_path / "Findings-update-pr-1234.json")
    assert envelope["source"] == "review"
    assert envelope["schema_version"] == _plugin_version()
    assert envelope["project"]["scope_slug"] == "pr-1234"
    assert len(envelope["findings"]) == 2
    for f in envelope["findings"]:
        assert "pr_comment" in f
        assert "content_hash" in f
    with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator(schema).validate(envelope)


def test_phase1_markdown_has_traceability_table(tmp_path):
    result = _run(
        [
            "--input",
            str(FIXTURES / "pre-render.phase1.sample.json"),
            "--out-dir",
            str(tmp_path),
            "--pr-number",
            "1234",
        ]
    )
    assert result.returncode == 0, result.stderr
    body = (tmp_path / "Findings-update-pr-1234.md").read_text(encoding="utf-8")
    assert "Review Traceability: PR 1234" in body
    assert "### reviewer1" in body
    assert "## Findings" in body
    assert "<I0>: Extract duplicated error-handling" in body
    # phase 1: no resolutions section yet
    assert "## Resolutions" not in body


def test_phase4_with_resolutions(tmp_path):
    pre = _load(FIXTURES / "pre-render.phase1.sample.json")
    pre["supplementary"]["resolutions"] = {
        "draft_replies": [
            {
                "reviewer": "reviewer1",
                "location": "src/handlers.py:42",
                "decision": "Accepted",
                "summary": "Too much duplication",
                "reply": "Good catch — extracted to handle_api_error in follow-up commit.",
            }
        ],
        "pending_local_edits": [
            {
                "reviewer": "reviewer1",
                "location": "src/handlers.py:42",
                "finding": "I0",
                "summary": "Extract duplicate try/except",
            }
        ],
        "no_action": [
            {"reviewer": "reviewer3", "summary": "Looks good overall!"}
        ],
    }
    # add resolution column in traceability table
    pre["supplementary"]["traceability"]["reviewer1"][0]["resolution"] = (
        "Pending — apply-review"
    )

    pre_path = tmp_path / "phase4.json"
    pre_path.write_text(json.dumps(pre), encoding="utf-8")

    result = _run(
        [
            "--input",
            str(pre_path),
            "--out-dir",
            str(tmp_path),
            "--pr-number",
            "1234",
        ]
    )
    assert result.returncode == 0, result.stderr

    envelope = _load(tmp_path / "Findings-update-pr-1234.json")
    with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator(schema).validate(envelope)

    body = (tmp_path / "Findings-update-pr-1234.md").read_text(encoding="utf-8")
    assert "## Resolutions" in body
    assert "### Draft Replies" in body
    assert "Pending — apply-review" in body  # table got the resolution column
    assert "### Pending Local Edits" in body
    assert "### No Action Needed" in body


def test_validation_failure_writes_no_files(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "id": "XX",  # invalid ID pattern
                        "title": "bad",
                        "severity": "important",
                        "locations": [{"path": "x", "line": "1"}],
                        "issue": "i",
                        "why_it_matters": "w",
                        "suggested_fix": "f",
                    }
                ]
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
            "--pr-number",
            "1",
        ]
    )
    assert result.returncode != 0
    assert not (tmp_path / "out" / "Findings-update-pr-1.json").exists()
