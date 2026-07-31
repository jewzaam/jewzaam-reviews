"""Schema validation tests for review-skill JSON contracts."""

import json
import sys
from pathlib import Path

import jsonschema
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.envelope import schema_registry  # noqa: E402
from scripts.resolve_schema import SCHEMA_PAIRS, resolve_schema  # noqa: E402


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate(schema: dict, instance: dict) -> None:
    jsonschema.Draft202012Validator(schema, registry=schema_registry()).validate(instance)


class TestAgentOutputSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "agent-output.schema.json")
        instance = _load_json(fixtures_dir / "agent-output.valid.json")
        _validate(schema, instance)

    def test_missing_locations_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "agent-output.schema.json")
        instance = _load_json(fixtures_dir / "agent-output.invalid-no-locations.json")
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, instance)

    def test_invalid_dimension_value_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "agent-output.schema.json")
        instance = _load_json(fixtures_dir / "agent-output.invalid-bad-confidence.json")
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, instance)


class TestConsolidatedSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "consolidated.schema.json")
        instance = _load_json(fixtures_dir / "consolidated.valid.json")
        _validate(schema, instance)

    def test_missing_content_hash_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "consolidated.schema.json")
        instance = _load_json(
            fixtures_dir / "consolidated.invalid-missing-content-hash.json"
        )
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, instance)


class TestStageEnvelopeSchema:
    def test_valid_envelope_passes(self, schemas_dir):
        schema = _load_json(schemas_dir / "stage-envelope.schema.json")
        instance = {
            "project": {"name": "myapp", "scope_slug": "pr-42"},
            "decomposition": [
                {"dimension_name": "auth", "dimension_slug": "auth"}
            ],
            "issues": [],
        }
        _validate(schema, instance)

    def test_missing_project_fails(self, schemas_dir):
        schema = _load_json(schemas_dir / "stage-envelope.schema.json")
        instance = {"decomposition": [], "issues": []}
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, instance)


class TestMergedFindingSchema:
    def test_valid_finding_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "merged-finding.schema.json")
        consolidated = _load_json(fixtures_dir / "consolidated.valid.json")
        finding = consolidated["findings"][0]
        _validate(schema, finding)

    def test_missing_content_hash_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "merged-finding.schema.json")
        consolidated = _load_json(fixtures_dir / "consolidated.valid.json")
        finding = dict(consolidated["findings"][0])
        del finding["content_hash"]
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, finding)


class TestValidationInputSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-input.schema.json")
        instance = _load_json(fixtures_dir / "validation-input.valid.json")
        _validate(schema, instance)

    def test_more_than_eight_findings_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-input.schema.json")
        instance = _load_json(fixtures_dir / "validation-input.invalid-too-many.json")
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, instance)


class TestResolvedSchemas:
    @pytest.mark.parametrize(
        "source_path,output_path", SCHEMA_PAIRS,
        ids=[p[0].stem for p in SCHEMA_PAIRS],
    )
    def test_no_refs_in_resolved(self, source_path, output_path):
        resolved = _load_json(output_path)
        refs = _find_refs(resolved)
        assert refs == [], f"{output_path.name} still contains $ref: {refs}"

    @pytest.mark.parametrize(
        "source_path,output_path", SCHEMA_PAIRS,
        ids=[p[0].stem for p in SCHEMA_PAIRS],
    )
    def test_resolved_is_fresh(self, source_path, output_path):
        expected = json.dumps(resolve_schema(source_path), indent=2, sort_keys=True) + "\n"
        actual = output_path.read_text()
        assert actual == expected, (
            f"{output_path.name} is stale. Run: make resolve-schemas"
        )

    @pytest.mark.parametrize(
        "source_path,output_path", SCHEMA_PAIRS,
        ids=[p[0].stem for p in SCHEMA_PAIRS],
    )
    def test_resolved_is_valid_json_schema(self, source_path, output_path):
        resolved = _load_json(output_path)
        jsonschema.Draft202012Validator.check_schema(resolved)


def _find_refs(node, path="") -> list[str]:
    """Recursively find all $ref keys in a JSON structure."""
    refs = []
    if isinstance(node, dict):
        if "$ref" in node:
            refs.append(f"{path}: {node['$ref']}")
        for k, v in node.items():
            refs.extend(_find_refs(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            refs.extend(_find_refs(item, f"{path}[{i}]"))
    return refs


class TestValidationOutputSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-output.schema.json")
        instance = _load_json(fixtures_dir / "validation-output.valid.json")
        _validate(schema, instance)

    def test_rescore_without_new_dimensions_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-output.schema.json")
        instance = _load_json(
            fixtures_dir / "validation-output.invalid-rescore-without-scores.json"
        )
        with pytest.raises(jsonschema.ValidationError):
            _validate(schema, instance)
