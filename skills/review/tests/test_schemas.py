"""Schema validation tests for review-skill JSON contracts."""

import json
from pathlib import Path

import jsonschema
import pytest


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class TestAgentOutputSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "agent-output.schema.json")
        instance = _load_json(fixtures_dir / "agent-output.valid.json")
        jsonschema.validate(instance=instance, schema=schema)

    def test_missing_locations_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "agent-output.schema.json")
        instance = _load_json(fixtures_dir / "agent-output.invalid-no-locations.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)

    def test_confidence_out_of_range_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "agent-output.schema.json")
        instance = _load_json(fixtures_dir / "agent-output.invalid-bad-confidence.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)


class TestConsolidatedSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "consolidated.schema.json")
        instance = _load_json(fixtures_dir / "consolidated.valid.json")
        jsonschema.validate(instance=instance, schema=schema)

    def test_missing_content_hash_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "consolidated.schema.json")
        instance = _load_json(
            fixtures_dir / "consolidated.invalid-missing-content-hash.json"
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)


class TestValidationInputSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-input.schema.json")
        instance = _load_json(fixtures_dir / "validation-input.valid.json")
        jsonschema.validate(instance=instance, schema=schema)

    def test_more_than_eight_findings_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-input.schema.json")
        instance = _load_json(fixtures_dir / "validation-input.invalid-too-many.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)


class TestValidationOutputSchema:
    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-output.schema.json")
        instance = _load_json(fixtures_dir / "validation-output.valid.json")
        jsonschema.validate(instance=instance, schema=schema)

    def test_rescore_without_new_scores_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "validation-output.schema.json")
        instance = _load_json(
            fixtures_dir / "validation-output.invalid-rescore-without-scores.json"
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)


class TestRenderConfigSchema:
    def test_default_config_passes(self, schemas_dir):
        schema = _load_json(schemas_dir / "render-config.schema.json")
        instance = _load_json(schemas_dir / "render-config.default.json")
        jsonschema.validate(instance=instance, schema=schema)

    def test_valid_fixture_passes(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "render-config.schema.json")
        instance = _load_json(fixtures_dir / "render-config.valid.json")
        jsonschema.validate(instance=instance, schema=schema)

    def test_invalid_fixture_fails(self, schemas_dir, fixtures_dir):
        schema = _load_json(schemas_dir / "render-config.schema.json")
        instance = _load_json(fixtures_dir / "render-config.invalid.json")
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=instance, schema=schema)
