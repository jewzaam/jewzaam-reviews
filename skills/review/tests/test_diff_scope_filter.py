"""Tests for scripts/diff-scope-filter.py."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "diff-scope-filter.py"
SCHEMAS = REPO_ROOT / "schemas"
PLUGIN_ROOT = REPO_ROOT.parent.parent

sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.envelope import schema_registry  # noqa: E402


def _assert_envelope_valid(envelope: dict) -> None:
    """The envelope this script writes must satisfy stage-envelope.schema.json.

    apply-verdicts.py validates the envelope it reads, so an envelope this
    script emits with an out-of-enum issue kind/severity breaks the pipeline
    one stage downstream.
    """
    with (SCHEMAS / "stage-envelope.schema.json").open() as fh:
        schema = json.load(fh)
    validator = jsonschema.Draft202012Validator(schema, registry=schema_registry())
    errors = sorted(validator.iter_errors(envelope), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    )


def _load_module():
    spec = importlib.util.spec_from_file_location("diff_scope_filter", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_stage_dir(stage_dir: Path, findings: list[dict]) -> None:
    stage_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "project": {"name": "myapp", "scope_slug": ""},
        "decomposition": [
            {
                "dimension_name": "x",
                "dimension_slug": "x",
                "dimension_scope": {},
            }
        ],
        "issues": [],
    }
    with (stage_dir / "_envelope.json").open("w", encoding="utf-8") as fh:
        json.dump(envelope, fh)
    for f in findings:
        p = stage_dir / f"{f['content_hash']}.json"
        with p.open("w", encoding="utf-8") as fh:
            json.dump(f, fh)


def _finding(
    *,
    chash: str,
    title: str = "test finding",
    path: str = "src/a.py",
    line: str = "10",
    role: str = "primary",
) -> dict:
    return {
        "content_hash": chash,
        "concern_slug": "implementation",
        "source_dimensions": ["x"],
        "title": title,
        "runtime_scope": "service-internal",
        "runtime_scope_justification": "test",
        "failure_mode": "degraded-behavior",
        "failure_mode_justification": "test",
        "evidence_quality": "demonstrated",
        "evidence_quality_justification": "test",
        "trace_origin": "component",
        "trace_origin_justification": "test",
        "effort_to_fix": "small",
        "effort_to_fix_justification": "test",
        "locations": [{"path": path, "line": line, "role": role}],
        "issue": "i",
        "why_it_matters": "w",
        "suggested_fix": "s",
    }


def _read_stage_dir(stage_dir: Path) -> tuple[dict, list[dict]]:
    with (stage_dir / "_envelope.json").open() as fh:
        envelope = json.load(fh)
    findings = []
    for p in sorted(stage_dir.glob("*.json")):
        if p.name == "_envelope.json":
            continue
        with p.open() as fh:
            findings.append(json.load(fh))
    return envelope, findings


# Diff where src/a.py lines 9-13 are changed
DIFF_OUTPUT = (
    "diff --git a/src/a.py b/src/a.py\n"
    "--- a/src/a.py\n"
    "+++ b/src/a.py\n"
    "@@ -8,0 +9,5 @@\n"
    "+new line 1\n"
    "+new line 2\n"
    "+new line 3\n"
    "+new line 4\n"
    "+new line 5\n"
)

NAME_STATUS_OUTPUT = ""


def _mock_run(cmd, **kwargs):
    if "--name-status" in cmd:
        return subprocess.CompletedProcess(cmd, 0, stdout=NAME_STATUS_OUTPUT, stderr="")
    if "-U0" in cmd:
        return subprocess.CompletedProcess(cmd, 0, stdout=DIFF_OUTPUT, stderr="")
    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected")


def _run_filter(stage_dir: Path, base_ref: str = "origin/main", mock_run=None) -> int:
    mod = _load_module()
    with patch.object(mod.subprocess, "run", side_effect=mock_run or _mock_run):
        return mod.main(["--stage-dir", str(stage_dir), "--base-ref", base_ref])


class TestNoBaseRef:
    def test_skips_when_no_base_ref(self, tmp_path: Path):
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, [_finding(chash="a" * 16)])
        mod = _load_module()
        rc = mod.main(["--stage-dir", str(stage), "--base-ref", ""])
        assert rc == 0
        _, findings = _read_stage_dir(stage)
        assert len(findings) == 1


class TestDiffScopeFilter:
    def test_keeps_finding_in_diff(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="a" * 16, path="src/a.py", line="10")])
        rc = _run_filter(stage)
        assert rc == 0
        _, findings = _read_stage_dir(stage)
        assert len(findings) == 1

    def test_removes_finding_outside_diff(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="b" * 16, path="src/a.py", line="1")])
        rc = _run_filter(stage)
        assert rc == 0
        envelope, findings = _read_stage_dir(stage)
        assert len(findings) == 0
        assert len(envelope["issues"]) == 1
        assert "diff_scope_filtered" in envelope["issues"][0]["message"]
        _assert_envelope_valid(envelope)

    def test_removes_finding_in_unmodified_file(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="c" * 16, path="src/b.py", line="5")])
        rc = _run_filter(stage)
        assert rc == 0
        _, findings = _read_stage_dir(stage)
        assert len(findings) == 0

    def test_mixed_findings_partial_filter(self, tmp_path: Path):
        stage = tmp_path / "merged"
        findings = [
            _finding(chash="a" * 16, path="src/a.py", line="10"),
            _finding(chash="b" * 16, path="src/a.py", line="1"),
            _finding(chash="c" * 16, path="src/b.py", line="5"),
        ]
        _write_stage_dir(stage, findings)
        rc = _run_filter(stage)
        assert rc == 0
        envelope, kept = _read_stage_dir(stage)
        assert len(kept) == 1
        assert kept[0]["content_hash"] == "a" * 16
        filtered = [i for i in envelope["issues"] if "diff_scope_filtered" in i["message"]]
        assert len(filtered) == 2
        _assert_envelope_valid(envelope)

    def test_new_file_keeps_all_findings(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="d" * 16, path="src/new.py", line="50")])

        def mock_with_new_file(cmd, **kwargs):
            if "--name-status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="A\tsrc/new.py\n", stderr="")
            if "-U0" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=DIFF_OUTPUT, stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        rc = _run_filter(stage, mock_run=mock_with_new_file)
        assert rc == 0
        _, findings = _read_stage_dir(stage)
        assert len(findings) == 1

    def test_line_range_overlap(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="e" * 16, path="src/a.py", line="8-11")])
        rc = _run_filter(stage)
        assert rc == 0
        _, findings = _read_stage_dir(stage)
        assert len(findings) == 1

    def test_line_range_no_overlap(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="f" * 16, path="src/a.py", line="1-8")])
        rc = _run_filter(stage)
        assert rc == 0
        _, findings = _read_stage_dir(stage)
        assert len(findings) == 0

    def test_all_findings_in_diff(self, tmp_path: Path):
        stage = tmp_path / "merged"
        findings = [
            _finding(chash="a" * 16, path="src/a.py", line="9"),
            _finding(chash="b" * 16, path="src/a.py", line="13"),
        ]
        _write_stage_dir(stage, findings)
        rc = _run_filter(stage)
        assert rc == 0
        _, kept = _read_stage_dir(stage)
        assert len(kept) == 2


class TestDownstreamCompatibility:
    """Regression: v0.7.5 emitted kind=diff_scope_filtered / severity=info,
    neither in findings.schema.json's issue enums, so apply-verdicts.py
    rejected the envelope its own upstream script had written."""

    def test_emitted_issues_satisfy_schema_enums(self, tmp_path: Path):
        stage = tmp_path / "merged"
        _write_stage_dir(stage, [_finding(chash="b" * 16, path="src/gone.py", line="1")])
        rc = _run_filter(stage)
        assert rc == 0
        envelope, _ = _read_stage_dir(stage)
        issue = envelope["issues"][0]
        assert issue["severity"] in ("error", "warning")
        assert issue["kind"] in (
            "permission_denied",
            "subagent_failure",
            "validation_failed",
            "tool_unavailable",
            "schema_rejected_input",
            "other",
        )
        _assert_envelope_valid(envelope)

    def test_apply_verdicts_accepts_filtered_envelope(self, tmp_path: Path):
        """End-to-end: filter → apply-verdicts must not reject the envelope."""
        stage = tmp_path / "10-merged"
        _write_stage_dir(
            stage,
            [
                _finding(chash="a" * 16, path="src/a.py", line="10"),
                _finding(chash="b" * 16, path="src/gone.py", line="1"),
            ],
        )
        assert _run_filter(stage) == 0

        verdicts = tmp_path / "15-validation"
        verdicts.mkdir()
        out = tmp_path / "20-findings"
        out.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "apply-verdicts.py"),
                "--input-dir", str(stage),
                "--verdicts-dir", str(verdicts),
                "--output-dir", str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        envelope, findings = _read_stage_dir(out)
        assert len(findings) == 1
        assert findings[0]["content_hash"] == "a" * 16
        # The filter's issue survived into the downstream envelope.
        assert any("diff_scope_filtered" in i["message"] for i in envelope["issues"])
