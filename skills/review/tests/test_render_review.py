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


def _create_stage_dir_from_fixture(stage_dir: Path, fixture_path: Path) -> None:
    """Convert a monolithic fixture JSON to a stage directory."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    with fixture_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    envelope = {
        "project": data.get("project", {"name": "myapp"}),
        "decomposition": data.get("decomposition", []),
        "issues": [],
    }
    with (stage_dir / "_envelope.json").open("w", encoding="utf-8") as fh:
        json.dump(envelope, fh)
    for finding in data.get("findings", []):
        ch = finding["content_hash"]
        with (stage_dir / f"{ch}.json").open("w", encoding="utf-8") as fh:
            json.dump(finding, fh)


class TestRenderReviewJson:
    def test_buckets_and_ids_assigned(self, tmp_path):
        stage = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage, FIXTURES / "post-validation.sample.json")
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
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
        stage = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage, FIXTURES / "post-validation.sample.json")
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
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
        stage = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage, FIXTURES / "post-validation.sample.json")
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (out_dir / "Findings-review.md").read_text(encoding="utf-8")
        assert "# Code Review: myapp" in body
        assert "## Findings" in body
        assert "### Critical" in body
        assert "C0" in body
        assert "SQL injection" in body
        assert "Findings-review-supplementary.md" in body

    def test_supplementary_lists_decomposition_and_needs_review(self, tmp_path):
        stage = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage, FIXTURES / "post-validation.sample.json")
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        body = (out_dir / "Findings-review-supplementary.md").read_text(encoding="utf-8")
        assert "## Decomposition" in body
        assert "auth subsystem" in body
        assert "## Detailed Analysis" in body
        assert "### Security" in body or "### security" in body.lower()
        assert "Maybe we should log here" in body


class TestSupplementaryCategorization:
    """Concern sections carry severity subsections, so a reader can tell a
    critical from a suggestion without decoding the ID prefix."""

    def _render(self, tmp_path):
        stage = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage, FIXTURES / "post-validation.sample.json")
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        return (
            (out_dir / "Findings-review.md").read_text(encoding="utf-8"),
            (out_dir / "Findings-review-supplementary.md").read_text(encoding="utf-8"),
            _load(out_dir / "Findings-review.json"),
        )

    def test_severity_subsections_under_each_concern(self, tmp_path):
        _main, supp, rendered = self._render(tmp_path)
        buckets_present = {f["severity"] for f in rendered["findings"]}
        for bucket in buckets_present:
            heading = f"#### {bucket.replace('-', ' ').title()}"
            assert heading in supp, f"missing {heading!r} in supplementary"
        # Concern stays the outer grouping; findings drop one level to make room.
        assert "### Security" in supp
        assert "##### C0:" in supp or "##### N0:" in supp

    def test_high_severity_findings_appear_in_both_files(self, tmp_path):
        main, supp, rendered = self._render(tmp_path)
        top = [
            f for f in rendered["findings"] if f["severity"] in ("critical", "important")
        ]
        assert top, "fixture must contain a critical or important finding"
        for f in top:
            assert f["title"] in main
            assert f["title"] in supp, "supplementary is the full per-concern view"

    def test_main_breaks_deferred_findings_out_by_concern(self, tmp_path):
        main, _supp, rendered = self._render(tmp_path)
        deferred = [
            f
            for f in rendered["findings"]
            if f["severity"] in ("suggestion", "needs-review")
        ]
        assert deferred, "fixture must contain a suggestion or needs-review finding"
        assert "| Concern | Suggestion | Needs review |" in main
        for concern in {f["concern_slug"] for f in deferred}:
            # Linked to its supplementary section, not just counted.
            assert (
                f"[{concern.title()}](Findings-review-supplementary.md#{concern})"
                in main
            )
        counts = {"suggestion": 0, "needs-review": 0}
        for f in deferred:
            counts[f["severity"]] += 1
        assert f"| **Total** | **{counts['suggestion']}** | **{counts['needs-review']}** |" in main

    def test_concern_links_resolve_to_supplementary_headings(self, tmp_path):
        main, supp, rendered = self._render(tmp_path)
        # An anchor that does not match a heading is a dead link in the
        # deliverable, and nothing else in the pipeline would catch it.
        for concern in {f["concern_slug"] for f in rendered["findings"]}:
            if f"#{concern})" in main:
                assert f"### {concern.title()}" in supp

    def test_empty_deferred_buckets_state_it(self, tmp_path):
        stage = tmp_path / "20-findings"
        stage.mkdir(parents=True)
        (stage / "_envelope.json").write_text(
            json.dumps(
                {
                    "project": {"name": "myapp"},
                    "decomposition": [
                        {"dimension_name": "full scope", "dimension_slug": "full-scope"}
                    ],
                    "issues": [],
                }
            )
        )
        finding = {
            "title": "Crash on empty input",
            "severity": "critical",
            "confidence": "high",
            "concern_slug": "implementation",
            "content_hash": "aaaaaaaaaaaaaaaa",
            "locations": [{"path": "app.py", "line": "3", "role": "primary"}],
            "issue": "x",
            "why_it_matters": "y",
            "suggested_fix": "z",
        }
        (stage / "aaaaaaaaaaaaaaaa.json").write_text(json.dumps(finding))
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
                "--scoring",
                "simple",
            ]
        )
        assert result.returncode == 0, result.stderr
        main = (out_dir / "Findings-review.md").read_text(encoding="utf-8")
        assert "No suggestions or low-confidence findings." in main
        assert "| Concern |" not in main


class TestSharedSchemaCompliance:
    def _render(self, tmp_path, extra_args=None, stage_dir=None):
        if stage_dir is None:
            stage_dir = tmp_path / "20-findings"
            _create_stage_dir_from_fixture(stage_dir, FIXTURES / "post-validation.sample.json")
        out_dir = tmp_path / "out"
        args = [
            "--input-dir",
            str(stage_dir),
            "--out-dir",
            str(out_dir),
            "--project-name",
            "myapp",
        ]
        if extra_args:
            args.extend(extra_args)
        return _run(args)

    def test_rendered_json_validates_against_shared_schema(self, tmp_path):
        result = self._render(tmp_path)
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "out" / "Findings-review.json")

        with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(rendered)

    def test_rendered_json_has_handoff_envelope(self, tmp_path):
        result = self._render(tmp_path)
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "out" / "Findings-review.json")
        assert rendered["schema_version"] == _plugin_version()
        assert rendered["source"] == "review"
        assert rendered["issues"] == []

    def test_issues_passthrough(self, tmp_path):
        stage = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage, FIXTURES / "post-validation.sample.json")
        # Inject issues into the stage envelope
        with (stage / "_envelope.json").open("r", encoding="utf-8") as fh:
            envelope = json.load(fh)
        envelope["issues"] = [
            {
                "severity": "warning",
                "kind": "subagent_failure",
                "message": "auth/security agent returned malformed JSON after 3 tries",
                "source_component": "security/auth",
            }
        ]
        with (stage / "_envelope.json").open("w", encoding="utf-8") as fh:
            json.dump(envelope, fh)
        result = self._render(tmp_path, stage_dir=stage)
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "out" / "Findings-review.json")
        assert len(rendered["issues"]) == 1
        assert rendered["issues"][0]["kind"] == "subagent_failure"

    def test_render_fails_on_invalid_input_and_writes_no_files(self, tmp_path):
        # Stage dir with a finding missing 'content_hash' — renderer
        # produces a shape that violates the shared schema.
        stage = tmp_path / "20-findings"
        stage.mkdir(parents=True, exist_ok=True)
        envelope = {
            "project": {"name": "myapp"},
            "decomposition": [
                {"dimension_name": "x", "dimension_slug": "x"}
            ],
            "issues": [],
        }
        with (stage / "_envelope.json").open("w", encoding="utf-8") as fh:
            json.dump(envelope, fh)
        bad_finding = {
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
        # Write finding without content_hash — use a placeholder filename
        with (stage / "no-hash.json").open("w", encoding="utf-8") as fh:
            json.dump(bad_finding, fh)
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode != 0
        assert "does not validate" in result.stderr
        assert not out_dir.exists() or not any(out_dir.iterdir())


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


class TestRenderReviewSimpleScoring:
    def _stage(self, tmp_path):
        stage = tmp_path / "20-findings"
        stage.mkdir(parents=True)
        envelope = {
            "project": {"name": "myapp"},
            "decomposition": [
                {"dimension_name": "full scope", "dimension_slug": "full-scope"}
            ],
            "issues": [],
        }
        (stage / "_envelope.json").write_text(json.dumps(envelope))
        findings = [
            {
                "title": "Crash on empty input",
                "severity": "critical",
                "confidence": "high",
                "concern_slug": "implementation",
                "content_hash": "aaaaaaaaaaaaaaaa",
                "locations": [{"path": "app.py", "line": "3", "role": "primary"}],
                "issue": "x",
                "why_it_matters": "y",
                "suggested_fix": "z",
            },
            {
                "title": "Speculative hunch",
                "severity": "suggestion",
                "confidence": "low",
                "concern_slug": "implementation",
                "content_hash": "bbbbbbbbbbbbbbbb",
                "locations": [{"path": "app.py", "line": "9", "role": "primary"}],
                "issue": "x",
                "why_it_matters": "y",
                "suggested_fix": "z",
            },
        ]
        for f in findings:
            (stage / f"{f['content_hash']}.json").write_text(json.dumps(f))
        return stage

    def test_simple_scoring_render(self, tmp_path):
        stage = self._stage(tmp_path)
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
                "--scoring",
                "simple",
            ]
        )
        assert result.returncode == 0, result.stderr
        rendered = _load(out_dir / "Findings-review.json")
        assert rendered["scoring"] == "simple"
        by_title = {f["title"]: f for f in rendered["findings"]}
        # Direct severity preserved; low confidence lands in needs-review.
        assert by_title["Crash on empty input"]["severity"] == "critical"
        assert by_title["Crash on empty input"]["id"] == "C0"
        assert by_title["Speculative hunch"]["severity"] == "needs-review"
        # Validates against the shared schema's simple branch.
        schema = _load(SHARED_SCHEMA)
        jsonschema.validate(instance=rendered, schema=schema)
        # Markdown shows confidence instead of the dimensions line.
        md = (out_dir / "Findings-review.md").read_text(encoding="utf-8")
        assert "**Confidence:** high" in md
        assert "runtime_scope=" not in md


class TestCrossCuttingObservationsRender:
    def test_observations_render_in_supplementary(self, tmp_path):
        stage = tmp_path / "20-findings"
        stage.mkdir(parents=True)
        envelope = {
            "project": {"name": "myapp"},
            "decomposition": [
                {"dimension_name": "full scope", "dimension_slug": "full-scope"}
            ],
            "issues": [],
            "cross_cutting_observations": [
                {"agent": "architecture/full-scope", "text": "Pattern A everywhere"}
            ],
        }
        (stage / "_envelope.json").write_text(json.dumps(envelope))
        out_dir = tmp_path / "out"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--out-dir",
                str(out_dir),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        rendered = _load(out_dir / "Findings-review.json")
        assert rendered["supplementary"]["cross_cutting_observations"] == [
            {"agent": "architecture/full-scope", "text": "Pattern A everywhere"}
        ]
        supp = (out_dir / "Findings-review-supplementary.md").read_text(
            encoding="utf-8"
        )
        assert "## Cross-Cutting Observations" in supp
        assert "Pattern A everywhere" in supp
        # Shared-schema validation still passes with the supplementary field.
        schema = _load(SHARED_SCHEMA)
        jsonschema.validate(instance=rendered, schema=schema)


class TestRunIdentity:
    """Findings trace back to their run after .tmp-review/ is wiped."""

    def _render(self, tmp_path, extra_args=None):
        stage_dir = tmp_path / "20-findings"
        _create_stage_dir_from_fixture(stage_dir, FIXTURES / "post-validation.sample.json")
        args = [
            "--input-dir",
            str(stage_dir),
            "--out-dir",
            str(tmp_path / "out"),
            "--project-name",
            "myapp",
        ]
        if extra_args:
            args.extend(extra_args)
        return _run(args)

    def test_ids_recorded_and_valid(self, tmp_path):
        result = self._render(
            tmp_path,
            ["--run-id", "abc123def456", "--orchestrating-session-id", "sess-xyz"],
        )
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "out" / "Findings-review.json")
        assert rendered["run_id"] == "abc123def456"
        assert rendered["orchestrating_session_id"] == "sess-xyz"
        with SHARED_SCHEMA.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.Draft202012Validator(schema).validate(rendered)

    def test_keys_absent_when_not_supplied(self, tmp_path):
        result = self._render(tmp_path)
        assert result.returncode == 0, result.stderr
        rendered = _load(tmp_path / "out" / "Findings-review.json")
        assert "run_id" not in rendered
        assert "orchestrating_session_id" not in rendered
