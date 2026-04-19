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


def _make_consolidated(findings: list[dict]) -> dict:
    return {
        "project": {"name": "myapp", "scope_slug": ""},
        "decomposition": [
            {
                "dimension_name": "x",
                "dimension_slug": "x",
                "dimension_scope": {},
            }
        ],
        "findings": findings,
    }


def _finding(
    *,
    chash: str,
    title: str,
    impact: int,
    likelihood: int,
    concern: str = "implementation",
) -> dict:
    return {
        "content_hash": chash,
        "concern_slug": concern,
        "source_dimensions": ["x"],
        "title": title,
        "impact": impact,
        "likelihood": likelihood,
        "effort_to_fix": 30,
        "confidence": 80,
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
                impact=50 + i,
                likelihood=50,
            )
            for i in range(20)
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(
            [
                "--input",
                str(consolidated),
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
            _finding(chash="0000000000000001", title="low", impact=10, likelihood=20),
            _finding(chash="0000000000000002", title="high", impact=90, likelihood=80),
            _finding(chash="0000000000000003", title="mid", impact=50, likelihood=50),
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(["--input", str(consolidated), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        batch1 = _load(out / "batch-1-input.json")
        titles = [f["title"] for f in batch1["findings"]]
        assert titles == ["high", "mid", "low"]

    def test_index_field_points_to_consolidated_findings_position(self, tmp_path: Path):
        """The `index` field MUST refer to the original position in
        consolidated.findings so verdicts can be applied with
        consolidated.findings[index]. Sorting MUST NOT renumber it."""
        findings = [
            _finding(chash="0000000000000010", title="A", impact=10, likelihood=10),
            _finding(chash="0000000000000020", title="B", impact=90, likelihood=90),
            _finding(chash="0000000000000030", title="C", impact=50, likelihood=50),
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(["--input", str(consolidated), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        batch1 = _load(out / "batch-1-input.json")
        # B should be first in priority order, but its index must be 1
        # (its original position in consolidated.findings).
        first = batch1["findings"][0]
        assert first["title"] == "B"
        assert first["index"] == 1
        # A has the lowest priority — index 0 (its original position).
        last = batch1["findings"][-1]
        assert last["title"] == "A"
        assert last["index"] == 0

    def test_batch_finding_has_only_schema_fields(self, tmp_path: Path):
        """source_dimensions (and any other consolidated-only field) must be
        stripped — validation-input schema sets additionalProperties: false."""
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(
                _make_consolidated(
                    [
                        _finding(
                            chash="aaaaaaaaaaaaaaaa",
                            title="t",
                            impact=50,
                            likelihood=50,
                        )
                    ]
                ),
                fh,
            )
        out = tmp_path / "validation"
        result = _run(["--input", str(consolidated), "--output-dir", str(out)])
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
                impact=50,
                likelihood=50,
            )
            for i in range(17)
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(["--input", str(consolidated), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        schema = _load(SCHEMAS / "validation-input.schema.json")
        for batch_file in sorted(out.glob("batch-*-input.json")):
            data = _load(batch_file)
            jsonschema.validate(instance=data, schema=schema)

    def test_custom_batch_size_respected(self, tmp_path: Path):
        findings = [
            _finding(
                chash=f"{i:016x}",
                title=f"f{i}",
                impact=50,
                likelihood=50,
            )
            for i in range(10)
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(
            [
                "--input",
                str(consolidated),
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
            _finding(chash=f"{i:016x}", title=f"f{i}", impact=50, likelihood=50)
            for i in range(3)
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(
            [
                "--input",
                str(consolidated),
                "--output-dir",
                str(out),
                "--batch-size",
                "9",
            ]
        )
        assert result.returncode != 0
        assert "8" in (result.stderr + result.stdout)

    def test_empty_findings_list(self, tmp_path: Path):
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated([]), fh)
        out = tmp_path / "validation"
        result = _run(["--input", str(consolidated), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        files = list(out.glob("batch-*-input.json"))
        assert files == []

    def test_priority_tie_break_is_deterministic(self, tmp_path: Path):
        """Equal-priority findings must sort by content_hash so two runs
        produce identical batches."""
        findings = [
            _finding(chash="bbbbbbbbbbbbbbbb", title="b", impact=50, likelihood=50),
            _finding(chash="aaaaaaaaaaaaaaaa", title="a", impact=50, likelihood=50),
            _finding(chash="cccccccccccccccc", title="c", impact=50, likelihood=50),
        ]
        consolidated = tmp_path / "consolidated.json"
        with consolidated.open("w", encoding="utf-8") as fh:
            json.dump(_make_consolidated(findings), fh)
        out = tmp_path / "validation"
        result = _run(["--input", str(consolidated), "--output-dir", str(out)])
        assert result.returncode == 0, result.stderr
        batch1 = _load(out / "batch-1-input.json")
        titles = [f["title"] for f in batch1["findings"]]
        assert titles == ["a", "b", "c"]
