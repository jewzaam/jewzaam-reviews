"""Tests for scripts/validate-findings.py."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate-findings.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


class TestValidateFindings:
    def test_valid_agent_output_exits_zero(self):
        result = _run([str(FIXTURES / "agent-output.valid.json")])
        assert result.returncode == 0, result.stderr

    def test_invalid_agent_output_exits_nonzero(self):
        result = _run([str(FIXTURES / "agent-output.invalid-no-locations.json")])
        assert result.returncode != 0
        assert "locations" in (result.stderr + result.stdout).lower()

    def test_explicit_schema_flag(self):
        result = _run(
            ["--schema", "consolidated", str(FIXTURES / "consolidated.valid.json")]
        )
        assert result.returncode == 0, result.stderr

    def test_unknown_schema_name_exits_nonzero(self):
        result = _run(
            ["--schema", "nonsense", str(FIXTURES / "agent-output.valid.json")]
        )
        assert result.returncode != 0

    def test_missing_file_exits_nonzero(self):
        result = _run([str(FIXTURES / "does-not-exist.json")])
        assert result.returncode != 0


class TestSchemaAutoDetectionByDirectory:
    """Live pipeline filenames don't carry schema-name prefixes; parent
    directory is the signal."""

    def _copy_fixture_as(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    def test_raw_dir_implies_agent_output(self, tmp_path):
        target = tmp_path / ".tmp-review" / "raw" / "architecture-auth.json"
        self._copy_fixture_as(FIXTURES / "agent-output.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "agent-output" in result.stdout

    def test_validation_input_dir_and_suffix(self, tmp_path):
        target = tmp_path / ".tmp-review" / "validation" / "batch-1-input.json"
        self._copy_fixture_as(FIXTURES / "validation-input.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "validation-input" in result.stdout

    def test_validation_output_dir_and_suffix(self, tmp_path):
        target = (
            tmp_path / ".tmp-review" / "validation" / "batch-1-output.json"
        )
        self._copy_fixture_as(FIXTURES / "validation-output.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "validation-output" in result.stdout

    def test_validation_dir_with_unknown_suffix_fails(self, tmp_path):
        target = (
            tmp_path / ".tmp-review" / "validation" / "batch-1-mystery.json"
        )
        self._copy_fixture_as(FIXTURES / "validation-input.valid.json", target)
        result = _run([str(target)])
        assert result.returncode != 0
        assert "schema" in (result.stderr + result.stdout).lower()

    def test_filename_prefix_still_wins_for_fixtures(self, tmp_path):
        """If both filename pattern and parent-dir signal, filename wins
        (preserves existing behaviour for test fixtures with explicit names)."""
        target = tmp_path / "raw" / "agent-output.valid.json"
        self._copy_fixture_as(FIXTURES / "agent-output.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "agent-output" in result.stdout

    def test_00_raw_dir_implies_agent_output(self, tmp_path):
        target = tmp_path / ".tmp-review" / "00-raw" / "architecture-auth.json"
        self._copy_fixture_as(FIXTURES / "agent-output.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "agent-output" in result.stdout

    def test_10_merged_envelope_implies_stage_envelope(self, tmp_path):
        target = tmp_path / ".tmp-review" / "10-merged" / "_envelope.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        import json
        envelope = {
            "project": {"name": "test"},
            "decomposition": [{"dimension_name": "x", "dimension_slug": "x"}],
            "issues": [],
        }
        target.write_text(json.dumps(envelope), encoding="utf-8")
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "stage-envelope" in result.stdout

    def test_10_merged_finding_implies_merged_finding(self, tmp_path):
        target = tmp_path / ".tmp-review" / "10-merged" / "a1b2c3d4e5f60718.json"
        self._copy_fixture_as(FIXTURES / "consolidated.valid.json", target)
        # Extract a single finding from the consolidated fixture
        import json
        with (FIXTURES / "consolidated.valid.json").open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        finding = data["findings"][0]
        target.write_text(json.dumps(finding), encoding="utf-8")
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "merged-finding" in result.stdout

    def test_20_findings_dir_implies_merged_finding(self, tmp_path):
        target = tmp_path / ".tmp-review" / "20-findings" / "a1b2c3d4e5f60718.json"
        import json
        with (FIXTURES / "consolidated.valid.json").open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        finding = data["findings"][0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(finding), encoding="utf-8")
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "merged-finding" in result.stdout

    def test_15_validation_dir_input(self, tmp_path):
        target = tmp_path / ".tmp-review" / "15-validation" / "batch-1-input.json"
        self._copy_fixture_as(FIXTURES / "validation-input.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "validation-input" in result.stdout

    def test_15_validation_dir_output(self, tmp_path):
        target = tmp_path / ".tmp-review" / "15-validation" / "batch-1-output.json"
        self._copy_fixture_as(FIXTURES / "validation-output.valid.json", target)
        result = _run([str(target)])
        assert result.returncode == 0, result.stderr
        assert "validation-output" in result.stdout

    def test_unknown_dir_still_requires_explicit_schema(self, tmp_path):
        target = tmp_path / "elsewhere" / "architecture-auth.json"
        self._copy_fixture_as(FIXTURES / "agent-output.valid.json", target)
        result = _run([str(target)])
        assert result.returncode != 0
        assert "schema" in (result.stderr + result.stdout).lower()
