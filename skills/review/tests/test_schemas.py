"""Schema validation tests for review-skill JSON contracts."""

import json
import sys
from pathlib import Path

import jsonschema
import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.envelope import schema_registry  # noqa: E402


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
