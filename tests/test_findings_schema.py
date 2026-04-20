"""Validation tests for the shared cross-skill findings schema."""

import json
from pathlib import Path

import jsonschema
import pytest


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def schema(shared_schemas_dir: Path) -> dict:
    return _load_json(shared_schemas_dir / "findings.schema.json")


class TestValidExamples:
    @pytest.mark.parametrize(
        "fixture",
        [
            "review.valid.json",
            "standards.valid.json",
            "c4-validation.valid.json",
            "apply-review.valid.json",
        ],
    )
    def test_fixture_passes(self, schema, shared_examples_dir: Path, fixture: str):
        instance = _load_json(shared_examples_dir / fixture)
        jsonschema.validate(instance=instance, schema=schema)


class TestInvalidExamples:
    @pytest.mark.parametrize(
        "fixture",
        [
            "review.invalid-missing-concern.json",
            "standards.invalid-bad-severity.json",
            "c4-validation.invalid-missing-verdict.json",
            "apply-review.invalid-findings-nonempty.json",
        ],
    )
    def test_fixture_fails(self, schema, shared_examples_dir: Path, fixture: str):
        instance = _load_json(shared_examples_dir / fixture)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)


class TestSourceDiscrimination:
    def test_review_requires_decomposition(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        del instance["decomposition"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)

    def test_standards_does_not_require_decomposition(
        self, schema, shared_examples_dir: Path
    ):
        instance = _load_json(shared_examples_dir / "standards.valid.json")
        assert "decomposition" not in instance
        jsonschema.validate(instance=instance, schema=schema)

    def test_apply_review_requires_applied(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "apply-review.valid.json")
        del instance["applied"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)

    def test_schema_version_must_be_semver(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        instance["schema_version"] = "not-a-version"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)

    def test_schema_version_may_vary_across_plugin_releases(
        self, schema, shared_examples_dir: Path
    ):
        """schema_version tracks plugin version — any valid semver is accepted
        at the schema layer. version-check.py enforces that it matches the
        current plugin version."""
        instance = _load_json(shared_examples_dir / "review.valid.json")
        for v in ("0.1.0", "0.2.0", "1.0.0", "2.3.4"):
            instance["schema_version"] = v
            jsonschema.validate(instance=instance, schema=schema)

    def test_unknown_source_rejected(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        instance["source"] = "unknown"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)


class TestIssuesArray:
    def test_issues_array_required(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        del instance["issues"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)

    def test_issues_may_be_empty(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        instance["issues"] = []
        jsonschema.validate(instance=instance, schema=schema)

    def test_issue_requires_message(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        instance["issues"] = [{"severity": "warning", "kind": "other"}]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)

    def test_unknown_issue_kind_rejected(self, schema, shared_examples_dir: Path):
        instance = _load_json(shared_examples_dir / "review.valid.json")
        instance["issues"] = [
            {"severity": "warning", "kind": "bogus", "message": "x"}
        ]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)
