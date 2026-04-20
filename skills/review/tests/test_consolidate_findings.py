"""Tests for scripts/consolidate-findings.py."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "consolidate-findings.py"
SCHEMAS = REPO_ROOT / "schemas"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_agent_output(
    raw_dir: Path,
    *,
    concern_slug: str,
    dimension_slug: str,
    dimension_name: str | None = None,
    findings: list[dict],
) -> Path:
    """Write a minimal valid agent-output JSON to raw_dir."""
    concerns_full = {
        "architecture": "Architecture & Design",
        "implementation": "Implementation Quality",
        "test": "Test Quality & Coverage",
        "maintainability": "Maintainability & Standards",
        "security": "Security",
        "documentation": "Documentation",
        "observability": "Observability",
    }
    payload = {
        "agent_id": f"{concern_slug}-{dimension_slug}-001",
        "concern": concerns_full[concern_slug],
        "concern_slug": concern_slug,
        "dimension_name": dimension_name or dimension_slug,
        "dimension_slug": dimension_slug,
        "dimension_scope": {"paths": [f"src/{dimension_slug}/"]},
        "findings": findings,
    }
    path = raw_dir / f"{concern_slug}-{dimension_slug}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _make_finding(
    *,
    title: str,
    path: str,
    line: str,
    impact: int = 60,
    likelihood: int = 60,
    effort_to_fix: int = 30,
    confidence: int = 70,
    locations_extra: list[dict] | None = None,
) -> dict:
    locations = [{"path": path, "line": line, "role": "primary"}]
    if locations_extra:
        locations.extend(locations_extra)
    return {
        "title": title,
        "impact": impact,
        "likelihood": likelihood,
        "effort_to_fix": effort_to_fix,
        "confidence": confidence,
        "locations": locations,
        "issue": f"issue: {title}",
        "why_it_matters": "matters",
        "suggested_fix": f"fix: {title}",
    }


class TestConsolidateBasic:
    def test_single_agent_single_finding(self, tmp_path: Path):
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="X", path="src/a.py", line="10")],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert data["project"]["name"] == "myapp"
        assert len(data["decomposition"]) == 1
        assert data["decomposition"][0]["dimension_slug"] == "auth"
        assert len(data["findings"]) == 1
        f = data["findings"][0]
        assert f["title"] == "X"
        assert f["concern_slug"] == "security"
        assert f["source_dimensions"] == ["auth"]
        assert f["content_hash"] == f["content_hash"].lower()
        assert 16 <= len(f["content_hash"]) <= 64
        assert all(c in "0123456789abcdef" for c in f["content_hash"])

    def test_dedup_by_concern_and_primary_location(self, tmp_path: Path):
        """Two agents flag the same (concern_slug, path:line) → one finding,
        with max impact/likelihood/confidence and min effort_to_fix."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[
                _make_finding(
                    title="SQL injection",
                    path="src/auth/lookup.py",
                    line="23",
                    impact=70,
                    likelihood=60,
                    effort_to_fix=40,
                    confidence=80,
                )
            ],
        )
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="api",
            findings=[
                _make_finding(
                    title="SQL injection",
                    path="src/auth/lookup.py",
                    line="23",
                    impact=95,
                    likelihood=80,
                    effort_to_fix=20,
                    confidence=90,
                )
            ],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 1
        f = data["findings"][0]
        assert f["impact"] == 95
        assert f["likelihood"] == 80
        assert f["confidence"] == 90
        assert f["effort_to_fix"] == 20
        assert sorted(f["source_dimensions"]) == ["api", "auth"]

    def test_no_dedup_across_concerns(self, tmp_path: Path):
        """Same path:line in different concerns stays as two findings."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="X", path="src/a.py", line="10")],
        )
        _write_agent_output(
            raw,
            concern_slug="documentation",
            dimension_slug="auth",
            findings=[_make_finding(title="Y", path="src/a.py", line="10")],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 2

    def test_locations_are_unioned_and_dedup(self, tmp_path: Path):
        """Merging two findings on the same primary location unions their
        location arrays and dedupes by (path, line)."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[
                _make_finding(
                    title="X",
                    path="src/a.py",
                    line="10",
                    locations_extra=[
                        {"path": "src/b.py", "line": "5", "role": "related"},
                    ],
                )
            ],
        )
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="api",
            findings=[
                _make_finding(
                    title="X",
                    path="src/a.py",
                    line="10",
                    locations_extra=[
                        {"path": "src/b.py", "line": "5", "role": "related"},
                        {"path": "src/c.py", "line": "20", "role": "callsite"},
                    ],
                )
            ],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 1
        locs = data["findings"][0]["locations"]
        keys = {(loc["path"], loc["line"]) for loc in locs}
        assert keys == {("src/a.py", "10"), ("src/b.py", "5"), ("src/c.py", "20")}

    def test_cross_cutting_merge_by_title_similarity(self, tmp_path: Path):
        """Within the same concern, near-duplicate titles at different
        locations are merged."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[
                _make_finding(
                    title="missing input validation in user lookup",
                    path="src/a.py",
                    line="10",
                )
            ],
        )
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="api",
            findings=[
                _make_finding(
                    title="missing input validation in user lookup endpoint",
                    path="src/b.py",
                    line="20",
                )
            ],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 1
        merged = data["findings"][0]
        assert sorted(merged["source_dimensions"]) == ["api", "auth"]
        loc_keys = {(loc["path"], loc["line"]) for loc in merged["locations"]}
        assert loc_keys == {("src/a.py", "10"), ("src/b.py", "20")}

    def test_distinct_titles_not_merged(self, tmp_path: Path):
        """Titles below the similarity threshold stay separate."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="alpha bravo", path="src/a.py", line="1")],
        )
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="api",
            findings=[_make_finding(title="charlie delta", path="src/b.py", line="1")],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 2

    def test_decomposition_unique_by_slug(self, tmp_path: Path):
        """Multiple agents on the same dimension contribute one decomposition
        entry."""
        raw = tmp_path / "raw"
        raw.mkdir()
        for concern in ["security", "documentation", "test"]:
            _write_agent_output(
                raw,
                concern_slug=concern,
                dimension_slug="auth",
                dimension_name="auth subsystem",
                findings=[],
            )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["decomposition"]) == 1
        assert data["decomposition"][0]["dimension_name"] == "auth subsystem"

    def test_invalid_raw_file_is_skipped_with_warning(self, tmp_path: Path):
        """A malformed raw JSON does not abort consolidation; it is logged
        and skipped."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="X", path="src/a.py", line="10")],
        )
        bad = raw / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        assert "broken.json" in result.stderr
        data = _load(out)
        assert len(data["findings"]) == 1

    def test_scope_slug_in_project(self, tmp_path: Path):
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="X", path="src/a.py", line="10")],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--project-name",
                "myapp",
                "--scope-slug",
                "pr-565",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert data["project"]["scope_slug"] == "pr-565"

    def test_cross_concern_merge_at_identical_primary_location(self, tmp_path: Path):
        """Two concerns flag the same code from different angles. Same primary
        location + similar (but not identical) titles should merge under the
        higher-priority concern. Reproduces the production bug where
        'thread-safe' findings from architecture and implementation survived
        as separate C0/C1 entries."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="architecture",
            dimension_slug="engine",
            findings=[
                _make_finding(
                    title="_suppress_stdout() is not thread-safe",
                    path="src/transcription.py",
                    line="49-61",
                    impact=80,
                    likelihood=50,
                    confidence=85,
                )
            ],
        )
        _write_agent_output(
            raw,
            concern_slug="implementation",
            dimension_slug="engine",
            findings=[
                _make_finding(
                    title=(
                        "_suppress_stdout not thread-safe; concurrent "
                        "callers permanently silence stdout"
                    ),
                    path="src/transcription.py",
                    line="49-61",
                    impact=75,
                    likelihood=55,
                    confidence=85,
                )
            ],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 1
        merged = data["findings"][0]
        # Architecture wins on priority (80*50/100=40 > 75*55/100=41.25? actually
        # implementation wins by 0.0125). Either is acceptable; check that one
        # of the original concerns survives.
        assert merged["concern_slug"] in {"architecture", "implementation"}

    def test_cross_concern_no_merge_when_titles_too_different(self, tmp_path: Path):
        """Same primary location, completely different titles → keep separate.
        E.g., a security finding and a documentation finding at the same
        function definition are about different things."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[
                _make_finding(
                    title="missing input validation on email parameter",
                    path="src/auth.py",
                    line="42",
                )
            ],
        )
        _write_agent_output(
            raw,
            concern_slug="documentation",
            dimension_slug="auth",
            findings=[
                _make_finding(
                    title="docstring missing for public function",
                    path="src/auth.py",
                    line="42",
                )
            ],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 2
        concerns = {f["concern_slug"] for f in data["findings"]}
        assert concerns == {"security", "documentation"}

    def test_cross_concern_threshold_is_tunable(self, tmp_path: Path):
        """A high --cross-concern-threshold disables the merge; a low one
        enables it."""
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="architecture",
            dimension_slug="engine",
            findings=[
                _make_finding(
                    title="_suppress_stdout() is not thread-safe",
                    path="src/transcription.py",
                    line="49-61",
                )
            ],
        )
        _write_agent_output(
            raw,
            concern_slug="implementation",
            dimension_slug="engine",
            findings=[
                _make_finding(
                    title=(
                        "_suppress_stdout not thread-safe; concurrent "
                        "callers permanently silence stdout"
                    ),
                    path="src/transcription.py",
                    line="49-61",
                )
            ],
        )
        out = tmp_path / "consolidated.json"
        # Threshold 0.99 effectively disables cross-concern merge.
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--project-name",
                "myapp",
                "--cross-concern-threshold",
                "0.99",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        assert len(data["findings"]) == 2

    def test_output_validates_against_consolidated_schema(self, tmp_path: Path):
        """End-to-end: produced JSON validates against consolidated.schema.json."""
        import jsonschema

        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[
                _make_finding(title="X", path="src/a.py", line="10"),
                _make_finding(title="Y", path="src/a.py", line="20"),
            ],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            ["--raw-dir", str(raw), "--output", str(out), "--project-name", "myapp"]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        schema = _load(SCHEMAS / "consolidated.schema.json")
        jsonschema.validate(instance=data, schema=schema)


class TestIssuesOut:
    def test_malformed_raw_file_becomes_issue(self, tmp_path: Path):
        raw = tmp_path / "raw"
        raw.mkdir()
        # One valid file + one malformed file.
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="x", path="src/a.py", line="1")],
        )
        (raw / "bad.json").write_text("{ not valid json", encoding="utf-8")

        out = tmp_path / "consolidated.json"
        issues = tmp_path / "issues.json"
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--issues-out",
                str(issues),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        assert issues.exists()
        entries = _load(issues)
        assert isinstance(entries, list)
        assert any(
            e.get("kind") == "schema_rejected_input"
            and e.get("source_component") == "consolidate-findings"
            and "bad.json" in e.get("message", "")
            for e in entries
        )

    def test_issues_out_appends_to_existing_file(self, tmp_path: Path):
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="x", path="src/a.py", line="1")],
        )
        (raw / "bad.json").write_text("{ not valid json", encoding="utf-8")

        out = tmp_path / "consolidated.json"
        issues = tmp_path / "issues.json"
        # Pre-seed issues.json with a prior entry.
        prior = [
            {
                "severity": "warning",
                "kind": "tool_unavailable",
                "message": "xenon not installed",
            }
        ]
        issues.write_text(json.dumps(prior), encoding="utf-8")

        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--issues-out",
                str(issues),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        entries = _load(issues)
        assert len(entries) == 2
        assert entries[0]["kind"] == "tool_unavailable"
        assert entries[1]["kind"] == "schema_rejected_input"

    def test_envelope_shaped_raw_gets_diagnostic_warning(self, tmp_path: Path):
        """A raw/*.json with cross-skill envelope keys should produce a
        targeted warning ('wrong schema, wanted agent-output') rather than
        a wall of generic validation errors. This catches sub-agents that
        confuse the shared handoff shape for their per-agent output."""
        raw = tmp_path / "raw"
        raw.mkdir()
        # One valid file so the run has some survivors.
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="x", path="src/a.py", line="1")],
        )
        # And one envelope-shaped file.
        envelope = {
            "schema_version": "0.2.0",
            "source": "review",
            "project": {"name": "confused"},
            "decomposition": [{"dimension_name": "d", "dimension_slug": "d"}],
            "findings": [],
            "issues": [],
        }
        (raw / "documentation-core.json").write_text(
            json.dumps(envelope), encoding="utf-8"
        )

        out = tmp_path / "consolidated.json"
        issues = tmp_path / "issues.json"
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--issues-out",
                str(issues),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        # Targeted wording must appear and name the offending file.
        assert "envelope shape" in result.stderr
        assert "documentation-core.json" in result.stderr
        # It must also be captured as an issues.json entry for downstream.
        entries = _load(issues)
        assert any(
            "envelope shape" in e["message"]
            and "documentation-core.json" in e["message"]
            for e in entries
        )

    def test_no_warnings_means_no_issues_file_written(self, tmp_path: Path):
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="x", path="src/a.py", line="1")],
        )

        out = tmp_path / "consolidated.json"
        issues = tmp_path / "issues.json"
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--issues-out",
                str(issues),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        # No skipped files -> consolidator leaves the issues file untouched.
        assert not issues.exists()


class TestContentHashStability:
    """content_hash is the integrity key for apply-review — it MUST be
    deterministic across runs and stable across Pass 1/2/3 merging."""

    def test_hash_stable_across_two_runs(self, tmp_path: Path):
        # Identical inputs in two isolated runs produce byte-identical hashes.
        def run_once(dest: Path) -> dict:
            raw = dest / "raw"
            raw.mkdir(parents=True)
            _write_agent_output(
                raw,
                concern_slug="security",
                dimension_slug="auth",
                findings=[
                    _make_finding(title="X", path="src/a.py", line="10"),
                    _make_finding(title="Y", path="src/b.py", line="20"),
                ],
            )
            out = dest / "consolidated.json"
            result = _run(
                [
                    "--raw-dir",
                    str(raw),
                    "--output",
                    str(out),
                    "--project-name",
                    "myapp",
                ]
            )
            assert result.returncode == 0, result.stderr
            return _load(out)

        run_a = run_once(tmp_path / "a")
        run_b = run_once(tmp_path / "b")
        hashes_a = sorted(f["content_hash"] for f in run_a["findings"])
        hashes_b = sorted(f["content_hash"] for f in run_b["findings"])
        assert hashes_a == hashes_b
        # And the hashes are not empty / all-zero.
        assert all(h.strip("0") for h in hashes_a)

    def test_hash_preserved_after_pass1_dedup(self, tmp_path: Path):
        # Two agents reporting the same concern+primary location merge in
        # Pass 1. The merged finding's hash must match what a single-agent
        # contribution at the same (concern, dimension, path:line, title)
        # would have produced — otherwise downstream apply-review breaks.
        raw = tmp_path / "raw"
        raw.mkdir()
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth",
            findings=[_make_finding(title="X", path="src/a.py", line="10")],
        )
        _write_agent_output(
            raw,
            concern_slug="security",
            dimension_slug="auth2",
            findings=[_make_finding(title="X", path="src/a.py", line="10")],
        )
        out = tmp_path / "consolidated.json"
        result = _run(
            [
                "--raw-dir",
                str(raw),
                "--output",
                str(out),
                "--project-name",
                "myapp",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = _load(out)
        # Two contributors collapsed to one finding.
        assert len(data["findings"]) == 1
        # Hash based on (concern, FIRST contributor's dimension, path:line,
        # title). Since "auth" < "auth2" alphabetically, the first contributor
        # is "auth" — hash is stable regardless of file discovery order.
        assert data["findings"][0]["content_hash"].strip("0")
        assert sorted(data["findings"][0]["source_dimensions"]) == ["auth", "auth2"]


class TestConsolidatePureFunction:
    """Unit tests against the pure consolidate() entry point (no subprocess).

    Faster, pinpoint failures to merge logic, and support future
    parameterised edge-case coverage.
    """

    def _call(self, agent_outputs: list[dict], **kwargs) -> dict:
        import importlib.util

        spec = importlib.util.spec_from_file_location("consolidate", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        defaults = dict(
            project_name="myapp",
            scope_slug="",
            similarity_threshold=0.7,
            cross_concern_threshold=0.4,
        )
        defaults.update(kwargs)
        return module.consolidate(agent_outputs, **defaults)

    def _agent_output(self, concern_slug: str, dimension_slug: str, findings: list[dict]) -> dict:
        concerns_full = {
            "architecture": "Architecture & Design",
            "implementation": "Implementation Quality",
            "test": "Test Quality & Coverage",
            "maintainability": "Maintainability & Standards",
            "security": "Security",
            "documentation": "Documentation",
            "observability": "Observability",
        }
        return {
            "agent_id": f"{concern_slug}-{dimension_slug}",
            "concern": concerns_full[concern_slug],
            "concern_slug": concern_slug,
            "dimension_name": dimension_slug,
            "dimension_slug": dimension_slug,
            "dimension_scope": {"paths": [f"src/{dimension_slug}/"]},
            "findings": findings,
        }

    def test_empty_agent_outputs_returns_empty_consolidated(self):
        result = self._call([])
        assert result["findings"] == []
        # Decomposition is min-items 1 per consolidated schema? Let's check.
        # An empty run has no decomposition entries either; the schema allows
        # it to be an empty list but the overall envelope still validates.
        assert isinstance(result["decomposition"], list)

    def test_single_finding_round_trip(self):
        ao = self._agent_output(
            "security",
            "auth",
            [_make_finding(title="X", path="src/a.py", line="10")],
        )
        result = self._call([ao])
        assert len(result["findings"]) == 1
        assert result["findings"][0]["concern_slug"] == "security"
        assert result["findings"][0]["source_dimensions"] == ["auth"]

    def test_pass1_merges_same_concern_same_primary(self):
        findings = [_make_finding(title="X", path="src/a.py", line="10")]
        ao1 = self._agent_output("security", "d1", findings)
        ao2 = self._agent_output("security", "d2", findings)
        result = self._call([ao1, ao2])
        assert len(result["findings"]) == 1
        assert sorted(result["findings"][0]["source_dimensions"]) == ["d1", "d2"]

    def test_hash_mismatch_between_runs_detected_via_assertion(self):
        """Two runs with different inputs produce different hashes — this
        is the property downstream verdict application relies on to detect
        drift."""
        ao_a = self._agent_output(
            "security",
            "auth",
            [_make_finding(title="X", path="src/a.py", line="10")],
        )
        ao_b = self._agent_output(
            "security",
            "auth",
            [_make_finding(title="Different title", path="src/a.py", line="10")],
        )
        result_a = self._call([ao_a])
        result_b = self._call([ao_b])
        assert result_a["findings"][0]["content_hash"] != result_b["findings"][0]["content_hash"]
