"""Tests for scripts/render-review.py."""

import json
import subprocess
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render-review.py"
SCHEMAS = REPO_ROOT / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

PLUGIN_ROOT = REPO_ROOT.parent.parent
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


class TestRenderReviewJson:
    def test_buckets_and_ids_assigned(self, tmp_path):
        out_dir = tmp_path
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),

                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr

        json_path = out_dir / "Findings-review.json"
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

                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
                "--scope-slug",
                "pr-565",
            ]
        )
        assert result.returncode == 0, result.stderr
        assert (out_dir / "Findings-review-pr-565.json").exists()


class TestRenderReviewMarkdown:
    def test_main_markdown_lists_critical_findings(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),

                "--out-dir",
                str(tmp_path),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (tmp_path / "Findings-review.md").read_text(encoding="utf-8")
        assert "# Code Review: myapp" in body
        assert "## Findings" in body
        assert "### Critical" in body
        assert "C0" in body
        assert "SQL injection" in body
        assert "Findings-review-supplementary.md" in body

    def test_supplementary_lists_decomposition_and_needs_review(self, tmp_path):
        result = _run(
            [
                "--input",
                str(FIXTURES / "post-validation.sample.json"),

                "--out-dir",
                str(tmp_path),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (tmp_path / "Findings-review-supplementary.md").read_text(encoding="utf-8")
        assert "## Decomposition" in body
        assert "auth subsystem" in body
        assert "## Needs Review" in body
        assert "Maybe we should log here" in body
        assert "## Detailed Analysis" in body
        assert "### Security" in body or "### security" in body.lower()


class TestSharedSchemaCompliance:
    def _render(self, tmp_path, extra_args=None):
        args = [
            "--input",
            str(FIXTURES / "post-validation.sample.json"),
            "--out-dir",
            str(tmp_path),
            "--project-name",
            "myapp",
        ]
        if extra_args:
            args.extend(extra_args)
        return _run(args)

    def test_rendered_json_validates_against_shared_schema(self, tmp_path):
        result = self._render(tmp_path)
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "Findings-review.json")

        with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(rendered)

    def test_rendered_json_has_handoff_envelope(self, tmp_path):
        result = self._render(tmp_path)
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "Findings-review.json")
        assert rendered["schema_version"] == _plugin_version()
        assert rendered["source"] == "review"
        assert rendered["issues"] == []

    def test_issues_passthrough(self, tmp_path):
        issues_path = tmp_path / "issues.json"
        issues_path.write_text(
            json.dumps(
                [
                    {
                        "severity": "warning",
                        "kind": "subagent_failure",
                        "message": "auth/security agent returned malformed JSON after 3 tries",
                        "source_component": "security/auth",
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = self._render(tmp_path, ["--issues", str(issues_path)])
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "Findings-review.json")
        assert len(rendered["issues"]) == 1
        assert rendered["issues"][0]["kind"] == "subagent_failure"

    def test_render_fails_on_invalid_input_and_writes_no_files(self, tmp_path):
        # post-validation data with a finding missing 'content_hash' — renderer
        # produces a shape that violates the shared schema.
        bad_input = tmp_path / "bad.json"
        bad_input.write_text(
            json.dumps(
                {
                    "project": {"name": "myapp"},
                    "decomposition": [
                        {"dimension_name": "x", "dimension_slug": "x"}
                    ],
                    "findings": [
                        {
                            "concern_slug": "security",
                            "source_dimensions": ["x"],
                            "title": "missing content_hash",
                            "runtime_scope": "service-external",
                            "runtime_scope_justification": "test",
                            "failure_mode": "data-loss-or-security",
                            "failure_mode_justification": "test",
                            "evidence_quality": "demonstrated",
                            "evidence_quality_justification": "test",
                            "trace_origin": "entry-point",
                            "trace_origin_justification": "test",
                            "effort_to_fix": "small",
                            "effort_to_fix_justification": "test",
                            "locations": [{"path": "a.py", "line": "1"}],
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
                str(bad_input),

                "--out-dir",
                str(tmp_path / "out"),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode != 0
        assert "does not validate" in result.stderr
        assert not (tmp_path / "out").exists() or not any(
            (tmp_path / "out").iterdir()
        )


class TestAssignBucket:
    """Direct unit tests for the categorical bucket classification logic."""

    def _module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("render_review", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _finding(
        self,
        *,
        runtime_scope: str = "service-internal",
        failure_mode: str = "degraded-behavior",
        evidence_quality: str = "demonstrated",
        trace_origin: str = "entry-point",
        effort_to_fix: str = "small",
    ) -> dict:
        return {
            "runtime_scope": runtime_scope,
            "failure_mode": failure_mode,
            "evidence_quality": evidence_quality,
            "trace_origin": trace_origin,
            "effort_to_fix": effort_to_fix,
        }

    def test_speculative_is_needs_review(self):
        mod = self._module()
        f = self._finding(evidence_quality="speculative")
        assert mod.assign_bucket(f) == "needs-review"

    def test_critical_external_data_loss_entry_point(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-external",
            failure_mode="data-loss-or-security",
            evidence_quality="demonstrated",
            trace_origin="entry-point",
        )
        assert mod.assign_bucket(f) == "critical"

    def test_critical_external_crash_entry_point(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-external",
            failure_mode="crash-or-outage",
            evidence_quality="demonstrated",
            trace_origin="entry-point",
        )
        assert mod.assign_bucket(f) == "critical"

    def test_critical_internal_data_loss_entry_point(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-internal",
            failure_mode="data-loss-or-security",
            evidence_quality="demonstrated",
            trace_origin="entry-point",
        )
        assert mod.assign_bucket(f) == "critical"

    def test_critical_requires_entry_point_trace(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-external",
            failure_mode="data-loss-or-security",
            evidence_quality="demonstrated",
            trace_origin="local",
        )
        assert mod.assign_bucket(f) == "suggestion"

    def test_important_demonstrated_entry_point_degraded(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-internal",
            failure_mode="degraded-behavior",
            evidence_quality="demonstrated",
            trace_origin="entry-point",
        )
        assert mod.assign_bucket(f) == "important"

    def test_important_demonstrated_component_crash(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-internal",
            failure_mode="crash-or-outage",
            evidence_quality="demonstrated",
            trace_origin="component",
        )
        assert mod.assign_bucket(f) == "important"

    def test_important_inferred_component_data_loss(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="service-external",
            failure_mode="data-loss-or-security",
            evidence_quality="inferred",
            trace_origin="component",
        )
        assert mod.assign_bucket(f) == "important"

    def test_important_ci_build_break_entry_point(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="ci",
            failure_mode="build-break",
            evidence_quality="demonstrated",
            trace_origin="entry-point",
        )
        assert mod.assign_bucket(f) == "important"

    def test_ci_confusion_is_suggestion(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="ci",
            failure_mode="confusion",
            evidence_quality="demonstrated",
            trace_origin="local",
        )
        assert mod.assign_bucket(f) == "suggestion"

    def test_documentation_is_suggestion(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="documentation",
            failure_mode="confusion",
            evidence_quality="demonstrated",
            trace_origin="local",
        )
        assert mod.assign_bucket(f) == "suggestion"

    def test_ci_unclear_is_suggestion(self):
        mod = self._module()
        f = self._finding(
            runtime_scope="ci",
            failure_mode="unclear",
            evidence_quality="demonstrated",
            trace_origin="local",
        )
        assert mod.assign_bucket(f) == "suggestion"
