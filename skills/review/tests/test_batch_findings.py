"""Tests for scripts/batch-findings.py."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "batch-findings.py"
SCHEMAS = REPO_ROOT / "schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_stage_dir(stage_dir: Path, findings: list[dict]) -> None:
    """Write a stage directory with _envelope.json + per-finding files."""
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
        finding_path = stage_dir / f"{f['content_hash']}.json"
        with finding_path.open("w", encoding="utf-8") as fh:
            json.dump(f, fh)


def _finding(
    *,
    chash: str,
    title: str,
    runtime_scope: str = "service-internal",
    failure_mode: str = "degraded-behavior",
    evidence_quality: str = "demonstrated",
    trace_origin: str = "component",
    concern: str = "implementation",
) -> dict:
    return {
        "content_hash": chash,
        "concern_slug": concern,
        "source_dimensions": ["x"],
        "title": title,
        "runtime_scope": runtime_scope,
        "runtime_scope_justification": "test",
        "failure_mode": failure_mode,
        "failure_mode_justification": "test",
        "evidence_quality": evidence_quality,
        "evidence_quality_justification": "test",
        "trace_origin": trace_origin,
        "trace_origin_justification": "test",
        "effort_to_fix": "small",
        "effort_to_fix_justification": "test",
        "locations": [{"path": "src/a.py", "line": "1", "role": "primary"}],
        "issue": "i",
        "why_it_matters": "w",
        "suggested_fix": "s",
    }


class TestBatchFindings:
    def test_creates_correct_number_of_batches(self, tmp_path: Path):
        findings = [
            _finding(
                chash=f"{i:016x}",
                title=f"f{i}",
            )
            for i in range(20)
        ]
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, findings)
        out = tmp_path / "validation"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--output-dir",
                str(out),
            ]
        )
        assert result.returncode == 0, result.stderr
        # 20 findings / 8 per batch = ceil(2.5) = 3
        files = sorted(out.glob("batch-*-input.json"))
        assert len(files) == 3
        # All batches reference the same total
        for f in files:
            data = _load(f)
            assert data["total_batches"] == 3

    def test_findings_sorted_by_priority_descending(self, tmp_path: Path):
        findings = [
            _finding(chash="0000000000000001", title="low", runtime_scope="documentation", failure_mode="unclear", evidence_quality="speculative", trace_origin="local"),
            _finding(chash="0000000000000002", title="high", runtime_scope="service-external", failure_mode="data-loss-or-security", evidence_quality="demonstrated", trace_origin="entry-point"),
            _finding(chash="0000000000000003", title="mid", runtime_scope="ci", failure_mode="build-break", evidence_quality="demonstrated", trace_origin="component"),
        ]
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, findings)
        out = tmp_path / "validation"
        result = _run(["--input-dir", str(stage), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        batch1 = _load(out / "batch-1-input.json")
        titles = [f["title"] for f in batch1["findings"]]
        assert titles == ["high", "mid", "low"]

    def test_batch_finding_has_only_schema_fields(self, tmp_path: Path):
        """source_dimensions (and any other consolidated-only field) must be
        stripped — validation-input schema sets additionalProperties: false."""
        stage = tmp_path / "10-merged"
        _write_stage_dir(
            stage,
            [
                _finding(
                    chash="aaaaaaaaaaaaaaaa",
                    title="t",
                )
            ],
        )
        out = tmp_path / "validation"
        result = _run(["--input-dir", str(stage), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        batch1 = _load(out / "batch-1-input.json")
        assert "source_dimensions" not in batch1["findings"][0]

    def test_output_validates_against_validation_input_schema(self, tmp_path: Path):
        import jsonschema

        # 17 findings → 3 batches (8 + 8 + 1)
        findings = [
            _finding(
                chash=f"{i:016x}",
                title=f"f{i}",
            )
            for i in range(17)
        ]
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, findings)
        out = tmp_path / "validation"
        result = _run(["--input-dir", str(stage), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        schema = _load(SCHEMAS / "validation-input.schema.json")
        from scripts.envelope import schema_registry
        validator = jsonschema.Draft202012Validator(schema, registry=schema_registry())
        for batch_file in sorted(out.glob("batch-*-input.json")):
            data = _load(batch_file)
            validator.validate(data)

    def test_custom_batch_size_respected(self, tmp_path: Path):
        findings = [
            _finding(
                chash=f"{i:016x}",
                title=f"f{i}",
            )
            for i in range(10)
        ]
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, findings)
        out = tmp_path / "validation"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--output-dir",
                str(out),
                "--batch-size",
                "4",
            ]
        )
        assert result.returncode == 0, result.stderr
        files = sorted(out.glob("batch-*-input.json"))
        # 10 / 4 = ceil(2.5) = 3
        assert len(files) == 3
        # First batch has 4, last batch has 2
        assert len(_load(files[0])["findings"]) == 4
        assert len(_load(files[-1])["findings"]) == 2

    def test_batch_size_above_eight_rejected(self, tmp_path: Path):
        """Schema caps maxItems at 8; the script must enforce or reject."""
        findings = [
            _finding(chash=f"{i:016x}", title=f"f{i}")
            for i in range(3)
        ]
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, findings)
        out = tmp_path / "validation"
        result = _run(
            [
                "--input-dir",
                str(stage),
                "--output-dir",
                str(out),
                "--batch-size",
                "9",
            ]
        )
        assert result.returncode != 0
        assert "8" in (result.stderr + result.stdout)

    def test_empty_findings_list(self, tmp_path: Path):
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, [])
        out = tmp_path / "validation"
        result = _run(["--input-dir", str(stage), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        files = list(out.glob("batch-*-input.json"))
        assert files == []

    def test_priority_tie_break_is_deterministic(self, tmp_path: Path):
        """Equal-priority findings must sort by content_hash so two runs
        produce identical batches."""
        findings = [
            _finding(chash="bbbbbbbbbbbbbbbb", title="b"),
            _finding(chash="aaaaaaaaaaaaaaaa", title="a"),
            _finding(chash="cccccccccccccccc", title="c"),
        ]
        stage = tmp_path / "10-merged"
        _write_stage_dir(stage, findings)
        out = tmp_path / "validation"
        result = _run(["--input-dir", str(stage), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        batch1 = _load(out / "batch-1-input.json")
        titles = [f["title"] for f in batch1["findings"]]
        assert titles == ["a", "b", "c"]
