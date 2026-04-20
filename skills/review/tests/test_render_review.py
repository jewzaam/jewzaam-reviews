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
                "--config",
                str(SCHEMAS / "render-config.default.json"),
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
        assert (out_dir / "Findings-review-pr-565.json").exists()


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
                "--config",
                str(SCHEMAS / "render-config.default.json"),
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
            "--config",
            str(SCHEMAS / "render-config.default.json"),
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
                            "impact": 80,
                            "likelihood": 80,
                            "effort_to_fix": 40,
                            "confidence": 90,
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
                "--config",
                str(SCHEMAS / "render-config.default.json"),
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
    """Direct unit tests for the bucket-boundary classification logic.

    These pin the off-by-one behaviour at each threshold of the default
    render-config.default.json:
        confidence_floor = 60
        critical = {min_priority: 40, min_impact: 70}
        important = {min_priority: 25}
    """

    DEFAULT_CONFIG = {
        "confidence_floor": 60,
        "critical": {"min_priority": 40, "min_impact": 70},
        "important": {"min_priority": 25},
    }

    def _module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("render_review", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _finding(
        self,
        *,
        impact: int,
        likelihood: int,
        confidence: int,
        effort_to_fix: int = 40,
    ) -> dict:
        return {
            "impact": impact,
            "likelihood": likelihood,
            "effort_to_fix": effort_to_fix,
            "confidence": confidence,
        }

    def test_confidence_at_floor_not_needs_review(self):
        # confidence == confidence_floor (60) must NOT go to needs-review;
        # only confidence < floor does.
        mod = self._module()
        f = self._finding(impact=80, likelihood=80, confidence=60)
        assert mod.assign_bucket(f, self.DEFAULT_CONFIG) != "needs-review"

    def test_confidence_below_floor_needs_review(self):
        mod = self._module()
        f = self._finding(impact=80, likelihood=80, confidence=59)
        assert mod.assign_bucket(f, self.DEFAULT_CONFIG) == "needs-review"

    def test_critical_at_min_priority_and_impact(self):
        # priority = 50*80/100 = 40 (at min_priority), impact >= 70 → critical
        mod = self._module()
        f = self._finding(impact=70, likelihood=58, confidence=90)  # 70*58/100 ≈ 40.6
        assert mod.assign_bucket(f, self.DEFAULT_CONFIG) == "critical"

    def test_critical_priority_below_threshold_drops_to_important(self):
        # priority just under critical threshold, still above important
        mod = self._module()
        f = self._finding(impact=70, likelihood=56, confidence=90)  # 70*56/100 = 39.2
        bucket = mod.assign_bucket(f, self.DEFAULT_CONFIG)
        assert bucket == "important"

    def test_critical_impact_below_min_drops_to_important(self):
        # High priority but impact < 70 → falls out of critical, lands on important
        mod = self._module()
        # impact=69, likelihood=80 → priority = 55.2 (>= important threshold)
        f = self._finding(impact=69, likelihood=80, confidence=90)
        assert mod.assign_bucket(f, self.DEFAULT_CONFIG) == "important"

    def test_important_at_min_priority(self):
        mod = self._module()
        # priority = 50*50/100 = 25 (exactly at important threshold)
        f = self._finding(impact=50, likelihood=50, confidence=70)
        assert mod.assign_bucket(f, self.DEFAULT_CONFIG) == "important"

    def test_important_below_min_priority_is_suggestion(self):
        mod = self._module()
        # priority = 48 * 50 / 100 = 24 (just under important min)
        f = self._finding(impact=48, likelihood=50, confidence=70)
        assert mod.assign_bucket(f, self.DEFAULT_CONFIG) == "suggestion"
