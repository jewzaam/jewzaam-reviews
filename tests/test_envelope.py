"""Tests for scripts/envelope.py — the shared findings-envelope library."""

import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from scripts import envelope  # noqa: E402


def test_plugin_version_matches_manifest():
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert envelope.plugin_version() == manifest["version"]


def test_load_shared_schema_returns_dict():
    schema = envelope.load_shared_schema()
    assert isinstance(schema, dict)
    assert schema.get("$schema", "").startswith("https://json-schema.org/")


class TestBuildEnvelope:
    def test_minimum_fields_for_apply_review(self):
        env = envelope.build_envelope(
            source="apply-review",
            project={"name": "sample"},
            findings=[],
            applied=[{"finding_id": "C0", "outcome": "applied"}],
        )
        assert env["schema_version"] == envelope.plugin_version()
        assert env["source"] == "apply-review"
        assert env["project"] == {"name": "sample"}
        assert env["findings"] == []
        assert env["issues"] == []
        assert env["applied"] == [{"finding_id": "C0", "outcome": "applied"}]
        assert "decomposition" not in env
        assert "supplementary" not in env

    def test_review_envelope_with_decomposition(self):
        env = envelope.build_envelope(
            source="review",
            project={"name": "sample"},
            decomposition=[{"dimension_name": "x", "dimension_slug": "x"}],
            findings=[],
            issues=[],
        )
        assert env["decomposition"] == [
            {"dimension_name": "x", "dimension_slug": "x"}
        ]
        assert "applied" not in env

    def test_supplementary_included_only_when_truthy(self):
        env_no = envelope.build_envelope(
            source="standards",
            project={"name": "sample"},
            supplementary={},  # empty dict is falsy to build_envelope
        )
        assert "supplementary" not in env_no

        env_yes = envelope.build_envelope(
            source="standards",
            project={"name": "sample"},
            supplementary={"tldr": "hi"},
        )
        assert env_yes["supplementary"] == {"tldr": "hi"}

    def test_none_findings_defaults_to_empty_list(self):
        env = envelope.build_envelope(
            source="review",
            project={"name": "sample"},
            decomposition=[{"dimension_name": "x", "dimension_slug": "x"}],
        )
        assert env["findings"] == []
        assert env["issues"] == []


class TestValidateEnvelope:
    def test_valid_envelope_passes(self):
        env = envelope.build_envelope(
            source="apply-review",
            project={"name": "sample"},
            findings=[],
            applied=[{"finding_id": "C0", "outcome": "applied"}],
        )
        envelope.validate_envelope(env)

    def test_invalid_envelope_raises(self):
        bad = {
            "schema_version": envelope.plugin_version(),
            "source": "apply-review",
            "project": {"name": "sample"},
            "findings": [],
            "issues": [],
            # missing required `applied[]` for source=apply-review
        }
        with pytest.raises(jsonschema.ValidationError):
            envelope.validate_envelope(bad)


class TestLoadIssuesFile:
    def test_none_returns_empty_list(self):
        assert envelope.load_issues_file(None) == []

    def test_loads_valid_array(self, tmp_path):
        p = tmp_path / "issues.json"
        payload = [
            {"severity": "warning", "kind": "other", "message": "x"}
        ]
        p.write_text(json.dumps(payload), encoding="utf-8")
        assert envelope.load_issues_file(p) == payload

    def test_non_list_raises(self, tmp_path):
        p = tmp_path / "issues.json"
        p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON array"):
            envelope.load_issues_file(p)


class TestFormatValidationError:
    def test_error_includes_path_and_message(self):
        schema = envelope.load_shared_schema()
        validator = jsonschema.Draft202012Validator(schema)
        # Trigger an error.
        bad = {"schema_version": "0.0.0", "source": "bad"}
        errors = list(validator.iter_errors(bad))
        assert errors, "fixture should produce at least one validation error"

        msg = envelope.format_validation_error(errors[0], "test-source")
        assert "test-source" in msg
        assert "findings.schema.json" in msg


class TestWriteStageDir:
    def test_wipes_stale_files_before_writing(self, tmp_path):
        stale = tmp_path / "stale_hash.json"
        stale.write_text('{"old": true}', encoding="utf-8")

        env = {"project": {"name": "test"}, "issues": []}
        findings = [{"content_hash": "abcd1234abcd1234", "title": "new"}]
        envelope.write_stage_dir(tmp_path, env, findings)

        assert not stale.exists(), "stale file should have been removed"
        assert (tmp_path / "abcd1234abcd1234.json").exists()
        assert (tmp_path / "_envelope.json").exists()

    def test_non_json_files_preserved(self, tmp_path):
        keep = tmp_path / ".gitignore"
        keep.write_text("*\n", encoding="utf-8")

        env = {"project": {"name": "test"}, "issues": []}
        envelope.write_stage_dir(tmp_path, env, [])

        assert keep.exists(), "non-json files should not be removed"

    def test_roundtrip_with_load(self, tmp_path):
        env = {"project": {"name": "test"}, "decomposition": [], "issues": []}
        findings = [
            {"content_hash": "aaaa1111bbbb2222", "title": "f1"},
            {"content_hash": "cccc3333dddd4444", "title": "f2"},
        ]
        envelope.write_stage_dir(tmp_path, env, findings)
        loaded_env, loaded_findings = envelope.load_stage_dir(tmp_path)

        assert loaded_env["project"] == env["project"]
        assert len(loaded_findings) == 2
        assert {f["content_hash"] for f in loaded_findings} == {
            "aaaa1111bbbb2222",
            "cccc3333dddd4444",
        }


class TestContentHash:
    def test_deterministic(self):
        assert envelope.content_hash("a", "b", "c") == envelope.content_hash("a", "b", "c")

    def test_different_inputs_produce_different_hashes(self):
        h1 = envelope.content_hash("common", "src/a.py:10", "title one")
        h2 = envelope.content_hash("common", "src/a.py:10", "title two")
        assert h1 != h2

    def test_output_shape(self):
        h = envelope.content_hash("a", "b")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_known_layout(self):
        # 'a|b|c' -> SHA-256 prefix 16. Verifies parts joined with '|'.
        import hashlib

        expected = hashlib.sha256(b"a|b|c").hexdigest()[:16]
        assert envelope.content_hash("a", "b", "c") == expected


class TestLineStart:
    def test_simple_number(self):
        assert envelope._line_start("12") == 12

    def test_range(self):
        assert envelope._line_start("12-20") == 12

    def test_empty_string(self):
        assert envelope._line_start("") == 0

    def test_non_numeric(self):
        assert envelope._line_start("abc") == 0

    def test_non_numeric_range(self):
        assert envelope._line_start("abc-def") == 0

    def test_leading_dash(self):
        assert envelope._line_start("-5") == 0

    def test_trailing_dash(self):
        assert envelope._line_start("5-") == 5

    def test_single_digit(self):
        assert envelope._line_start("1") == 1

    def test_large_number(self):
        assert envelope._line_start("99999") == 99999


class TestAssignIdsPerBucket:
    def _f(self, severity, title, path="x.py", line="1"):
        return {
            "severity": severity,
            "title": title,
            "locations": [{"path": path, "line": line}],
        }

    def test_three_bucket_assignment(self):
        findings = [
            self._f("important", "b"),
            self._f("critical", "a"),
            self._f("suggestion", "c"),
            self._f("critical", "d"),
        ]
        out = envelope.assign_ids_per_bucket(
            findings,
            bucket_order=["critical", "important", "suggestion"],
            prefix_map={"critical": "C", "important": "I", "suggestion": "S"},
        )
        assert [f["id"] for f in out] == ["C0", "C1", "I0", "S0"]
        # Order within output respects bucket_order, then sort key.
        assert out[0]["title"] == "a"
        assert out[1]["title"] == "d"

    def test_four_bucket_assignment_for_review(self):
        findings = [
            self._f("needs-review", "low-confidence"),
            self._f("critical", "a"),
        ]
        out = envelope.assign_ids_per_bucket(
            findings,
            bucket_order=["critical", "important", "suggestion", "needs-review"],
            prefix_map={
                "critical": "C",
                "important": "I",
                "suggestion": "S",
                "needs-review": "N",
            },
        )
        assert [f["id"] for f in out] == ["C0", "N0"]

    def test_custom_sort_key(self):
        findings = [
            {"severity": "critical", "title": "z", "subdomain": "common"},
            {"severity": "critical", "title": "a", "subdomain": "python"},
        ]
        out = envelope.assign_ids_per_bucket(
            findings,
            bucket_order=["critical"],
            prefix_map={"critical": "C"},
            sort_key=lambda f: (f["subdomain"], f["title"]),
        )
        # 'common' sorts before 'python'; title 'z' wins over 'a' because
        # subdomain takes priority.
        assert out[0]["title"] == "z"
        assert out[1]["title"] == "a"

    def test_unknown_severity_raises(self):
        findings = [self._f("blocker", "bad")]
        with pytest.raises(ValueError, match="not in bucket_order"):
            envelope.assign_ids_per_bucket(
                findings,
                bucket_order=["critical", "important", "suggestion"],
                prefix_map={"critical": "C", "important": "I", "suggestion": "S"},
            )

    def test_empty_bucket_produces_no_ids(self):
        findings = [self._f("critical", "a")]
        out = envelope.assign_ids_per_bucket(
            findings,
            bucket_order=["critical", "important"],
            prefix_map={"critical": "C", "important": "I"},
        )
        assert [f["id"] for f in out] == ["C0"]
