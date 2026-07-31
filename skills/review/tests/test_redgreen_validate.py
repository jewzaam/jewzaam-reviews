"""Tests for scripts/redgreen-validate.py."""

import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(PLUGIN_ROOT))

from scripts.envelope import schema_registry  # noqa: E402

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "redgreen_validate",
    REPO_ROOT / "scripts" / "redgreen-validate.py",
)
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)


def _load_merged_finding_schema():
    with (SCHEMAS_DIR / "merged-finding.schema.json").open() as f:
        return json.load(f)


def _validate_finding(finding: dict) -> None:
    schema = _load_merged_finding_schema()
    validator = jsonschema.Draft202012Validator(schema, registry=schema_registry())
    validator.validate(finding)


class TestFindingFactories:
    def test_untested_change_validates(self):
        f = rg._untested_change_finding(["src/auth.py", "src/api.py"])
        _validate_finding(f)
        assert f["concern_slug"] == "test"
        assert f["runtime_scope"] == "service-external"
        assert f["failure_mode"] == "data-loss-or-security"
        assert len(f["locations"]) == 2

    def test_untested_change_includes_all_locations(self):
        files = [f"src/f{i}.py" for i in range(10)]
        f = rg._untested_change_finding(files)
        _validate_finding(f)
        assert len(f["locations"]) == 10

    def test_test_passes_before_fix_validates(self):
        f = rg._test_passes_before_fix_finding("tests/test_auth.py")
        _validate_finding(f)
        assert f["locations"][0]["path"] == "tests/test_auth.py"
        assert f["failure_mode"] == "data-loss-or-security"

    def test_test_fails_after_fix_validates(self):
        f = rg._test_fails_after_fix_finding("tests/test_api.py")
        _validate_finding(f)
        assert f["failure_mode"] == "build-break"
        assert f["runtime_scope"] == "ci"

    def test_tests_unrunnable_validates(self):
        files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]
        f = rg._tests_unrunnable_finding(files)
        _validate_finding(f)
        assert f["locations"][0]["role"] == "primary"
        assert len(f["locations"]) == 3

    def test_content_hashes_are_unique(self):
        hashes = {
            rg._untested_change_finding(["src/a.py"])["content_hash"],
            rg._test_passes_before_fix_finding("tests/t.py")["content_hash"],
            rg._test_fails_after_fix_finding("tests/t.py")["content_hash"],
            rg._tests_unrunnable_finding(["tests/t.py"])["content_hash"],
        }
        assert len(hashes) == 4


class TestTestFilePattern:
    def test_matches_test_prefix(self):
        assert rg.TEST_FILE_PATTERN.search("tests/test_auth.py")
        assert rg.TEST_FILE_PATTERN.search("test_foo.py")

    def test_matches_test_suffix(self):
        assert rg.TEST_FILE_PATTERN.search("src/auth_test.py")

    def test_rejects_non_test(self):
        assert not rg.TEST_FILE_PATTERN.search("src/auth.py")
        assert not rg.TEST_FILE_PATTERN.search("src/testing_utils.py")

    def test_rejects_non_python(self):
        assert not rg.TEST_FILE_PATTERN.search("test_foo.js")


class TestEvaluateResults:
    def test_validated_produces_no_findings(self):
        red = {"tests/test_a.py": ("fail", "FAILED")}
        green = {"tests/test_a.py": ("pass", "1 passed")}
        assert rg.evaluate_results(red, green) == []

    def test_both_pass_produces_passes_before_fix(self):
        red = {"tests/test_a.py": ("pass", "1 passed")}
        green = {"tests/test_a.py": ("pass", "1 passed")}
        findings = rg.evaluate_results(red, green)
        assert len(findings) == 1
        assert "passes before fix" in findings[0]["title"].lower()

    def test_both_fail_produces_single_unrunnable(self):
        red = {
            "tests/test_a.py": ("fail", "error"),
            "tests/test_b.py": ("fail", "error"),
        }
        green = {
            "tests/test_a.py": ("fail", "error"),
            "tests/test_b.py": ("fail", "error"),
        }
        findings = rg.evaluate_results(red, green)
        assert len(findings) == 1
        assert "cannot run" in findings[0]["title"].lower()

    def test_pass_then_fail_produces_fails_after_fix(self):
        red = {"tests/test_a.py": ("pass", "1 passed")}
        green = {"tests/test_a.py": ("fail", "FAILED")}
        findings = rg.evaluate_results(red, green)
        assert len(findings) == 1
        assert "fails after fix" in findings[0]["title"].lower()

    def test_mixed_results(self):
        red = {
            "tests/test_good.py": ("fail", ""),
            "tests/test_bad.py": ("pass", ""),
            "tests/test_broken.py": ("fail", ""),
        }
        green = {
            "tests/test_good.py": ("pass", ""),
            "tests/test_bad.py": ("pass", ""),
            "tests/test_broken.py": ("fail", ""),
        }
        findings = rg.evaluate_results(red, green)
        titles = [f["title"].lower() for f in findings]
        assert any("passes before fix" in t for t in titles)
        assert any("cannot run" in t for t in titles)
        assert not any("fails after fix" in t for t in titles)
        assert len(findings) == 2

    def test_all_outcomes_produce_valid_schema(self):
        red = {
            "tests/test_a.py": ("pass", ""),
            "tests/test_b.py": ("fail", ""),
            "tests/test_c.py": ("pass", ""),
        }
        green = {
            "tests/test_a.py": ("pass", ""),
            "tests/test_b.py": ("fail", ""),
            "tests/test_c.py": ("fail", ""),
        }
        findings = rg.evaluate_results(red, green)
        assert len(findings) == 3
        for f in findings:
            _validate_finding(f)

    def test_empty_results_no_findings(self):
        assert rg.evaluate_results({}, {}) == []

    def test_unrunnable_count_in_title_matches_file_count(self):
        red = {f"tests/test_{i}.py": ("fail", "") for i in range(7)}
        green = {f"tests/test_{i}.py": ("fail", "") for i in range(7)}
        findings = rg.evaluate_results(red, green)
        assert len(findings) == 1
        assert "7 test file" in findings[0]["title"]

    def test_untested_change_single_file(self):
        f = rg._untested_change_finding(["src/only.py"])
        _validate_finding(f)
        assert len(f["locations"]) == 1
        assert f["locations"][0]["role"] == "primary"


class TestSourceFilePattern:
    def test_matches_python(self):
        assert rg.SOURCE_FILE_PATTERN.search("src/auth.py")

    def test_rejects_non_python(self):
        assert not rg.SOURCE_FILE_PATTERN.search("README.md")
        assert not rg.SOURCE_FILE_PATTERN.search("Makefile")
