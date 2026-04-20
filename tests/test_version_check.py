"""Tests for scripts/version-check.py.

The script mixes pure functions (version extraction, semver validation,
file-to-file match) with git-based comparisons (merge-base, diff). Tests
here cover the pure and file-reading pieces; the git comparison is
exercised end-to-end against the repo's real git state but only verified
at the exit-code level (no synthetic-repo fixtures).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "version-check.py"


def _run(args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(args or [])],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class TestHappyPath:
    def test_current_repo_state_exits_cleanly(self):
        """Running against the repo as-is must exit 0 (PASS) or 1 (clean FAIL)
        and emit a structured summary line. The exact outcome is state-dependent
        — the working-tree gate FAILs when schemas/ or skills/ have uncommitted
        changes without a version bump, so this test cannot assume clean trees.
        It only guards against the script crashing or emitting no summary."""
        result = _run()
        assert result.returncode in (0, 1), (
            f"unexpected crash:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        if result.returncode == 0:
            assert "version-check: PASS" in result.stdout
        else:
            assert "version-check: FAIL" in result.stderr


class TestWorkingTreeGate:
    """Uncommitted working-tree changes in source_dirs must be treated as
    'source changed' for the bump check (preflight-before-commit use case)."""

    def test_uncommitted_changes_without_bump_exits_nonzero(
        self, monkeypatch, tmp_path
    ):
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        plugin_dir = tmp_path / ".claude-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"version": "0.2.0"}), encoding="utf-8"
        )
        (plugin_dir / "marketplace.json").write_text(
            json.dumps(
                {"plugins": [{"name": "jewzaam-reviews", "version": "0.2.0"}]}
            ),
            encoding="utf-8",
        )
        examples = tmp_path / "schemas" / "examples"
        examples.mkdir(parents=True)
        (examples / "aligned.valid.json").write_text(
            json.dumps({"schema_version": "0.2.0"}), encoding="utf-8"
        )

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "PLUGIN_JSON", plugin_dir / "plugin.json")
        monkeypatch.setattr(
            mod, "MARKETPLACE_JSON", plugin_dir / "marketplace.json"
        )
        monkeypatch.setattr(mod, "SCHEMA_EXAMPLES_DIR", examples)

        # HEAD == mainline (merge-base returns HEAD), so committed diff is
        # empty — only the working-tree gate can fire.
        monkeypatch.setattr(mod, "find_mainline", lambda: "origin/main")
        monkeypatch.setattr(
            mod, "_git", lambda *a, **kw: "deadbeef" if a and a[0] == "merge-base" else ""
        )
        monkeypatch.setattr(
            mod, "source_changed", lambda base, head, source_dirs: False
        )
        monkeypatch.setattr(
            mod, "working_tree_changed", lambda source_dirs: True
        )
        monkeypatch.setattr(mod, "version_at_revision", lambda rev: "0.2.0")

        exit_code = mod.main([])
        assert exit_code == 1


class TestVersionMismatch:
    def test_detects_plugin_vs_marketplace_mismatch(self, monkeypatch, tmp_path):
        """Render a copy of the repo with mismatched versions and run the
        script against it. We do this by pointing the script at a
        temporary copy of `.claude-plugin/`."""
        # Copy the real .claude-plugin/ to tmp, then mutate marketplace.json.
        src = REPO_ROOT / ".claude-plugin"
        dst = tmp_path / ".claude-plugin"
        dst.mkdir()
        for name in ("plugin.json", "marketplace.json"):
            (dst / name).write_text((src / name).read_text(encoding="utf-8"), encoding="utf-8")

        # Tweak marketplace.json to mismatch plugin.json.
        marketplace = json.loads((dst / "marketplace.json").read_text(encoding="utf-8"))
        marketplace["plugins"][0]["version"] = "9.9.9"
        (dst / "marketplace.json").write_text(
            json.dumps(marketplace, indent=2), encoding="utf-8"
        )

        # Import the script as a module and swap the constants.
        # Hyphen in the filename blocks plain `import`; load via importlib.
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        monkeypatch.setattr(mod, "PLUGIN_JSON", dst / "plugin.json")
        monkeypatch.setattr(mod, "MARKETPLACE_JSON", dst / "marketplace.json")
        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)

        exit_code = mod.main([])
        assert exit_code == 1


class TestInvalidSemver:
    def test_detects_invalid_semver(self, monkeypatch, tmp_path):
        src = REPO_ROOT / ".claude-plugin"
        dst = tmp_path / ".claude-plugin"
        dst.mkdir()
        plugin = json.loads((src / "plugin.json").read_text(encoding="utf-8"))
        plugin["version"] = "v1.2"  # invalid — has prefix and only 2 parts
        (dst / "plugin.json").write_text(json.dumps(plugin, indent=2), encoding="utf-8")

        marketplace = json.loads((src / "marketplace.json").read_text(encoding="utf-8"))
        marketplace["plugins"][0]["version"] = "v1.2"
        (dst / "marketplace.json").write_text(
            json.dumps(marketplace, indent=2), encoding="utf-8"
        )

        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        monkeypatch.setattr(mod, "PLUGIN_JSON", dst / "plugin.json")
        monkeypatch.setattr(mod, "MARKETPLACE_JSON", dst / "marketplace.json")

        exit_code = mod.main([])
        assert exit_code == 1


class TestSemverRegex:
    @pytest.mark.parametrize(
        "version",
        ["0.1.0", "1.0.0", "0.2.0", "10.20.30", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0+build.1"],
    )
    def test_valid_semver(self, version):
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.SEMVER_RE.match(version) is not None

    @pytest.mark.parametrize("version", ["v1.0.0", "1.0", "1.0.0.0", "01.0.0", "abc"])
    def test_invalid_semver(self, version):
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.SEMVER_RE.match(version) is None


class TestFixtureAlignment:
    def test_fixture_schema_version_drift_fails(self, monkeypatch, tmp_path):
        """A fixture whose schema_version doesn't match the plugin version
        must be flagged by version-check."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Synthetic repo root with a single misaligned fixture.
        plugin_dir = tmp_path / ".claude-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"version": "0.2.0"}), encoding="utf-8"
        )
        (plugin_dir / "marketplace.json").write_text(
            json.dumps(
                {"plugins": [{"name": "jewzaam-reviews", "version": "0.2.0"}]}
            ),
            encoding="utf-8",
        )
        examples = tmp_path / "schemas" / "examples"
        examples.mkdir(parents=True)
        (examples / "stale.valid.json").write_text(
            json.dumps({"schema_version": "0.1.0"}), encoding="utf-8"
        )
        (examples / "aligned.valid.json").write_text(
            json.dumps({"schema_version": "0.2.0"}), encoding="utf-8"
        )

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "PLUGIN_JSON", plugin_dir / "plugin.json")
        monkeypatch.setattr(mod, "MARKETPLACE_JSON", plugin_dir / "marketplace.json")
        monkeypatch.setattr(mod, "SCHEMA_EXAMPLES_DIR", examples)

        result = mod._find_misaligned_fixtures("0.2.0")
        assert len(result) == 1
        assert result[0][0].name == "stale.valid.json"
        assert result[0][1] == "0.1.0"

    def test_misaligned_fixture_causes_main_to_exit_nonzero(
        self, monkeypatch, tmp_path
    ):
        """Wire-up test for I39: _find_misaligned_fixtures returning a
        non-empty list must propagate into main() exit code 1."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        plugin_dir = tmp_path / ".claude-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"version": "0.2.0"}), encoding="utf-8"
        )
        (plugin_dir / "marketplace.json").write_text(
            json.dumps(
                {"plugins": [{"name": "jewzaam-reviews", "version": "0.2.0"}]}
            ),
            encoding="utf-8",
        )
        examples = tmp_path / "schemas" / "examples"
        examples.mkdir(parents=True)
        # One misaligned fixture is enough to trip the gate.
        (examples / "stale.valid.json").write_text(
            json.dumps({"schema_version": "0.1.0"}), encoding="utf-8"
        )

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "PLUGIN_JSON", plugin_dir / "plugin.json")
        monkeypatch.setattr(
            mod, "MARKETPLACE_JSON", plugin_dir / "marketplace.json"
        )
        monkeypatch.setattr(mod, "SCHEMA_EXAMPLES_DIR", examples)

        exit_code = mod.main([])
        assert exit_code == 1


class TestBumpRequired:
    """I38: the bump-required branch in main() (source changed but version
    did not) is now exercised end-to-end."""

    def test_source_changed_without_bump_exits_nonzero(
        self, monkeypatch, tmp_path
    ):
        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        plugin_dir = tmp_path / ".claude-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps({"version": "0.2.0"}), encoding="utf-8"
        )
        (plugin_dir / "marketplace.json").write_text(
            json.dumps(
                {"plugins": [{"name": "jewzaam-reviews", "version": "0.2.0"}]}
            ),
            encoding="utf-8",
        )
        # Aligned fixtures so the earlier gate passes.
        examples = tmp_path / "schemas" / "examples"
        examples.mkdir(parents=True)
        (examples / "aligned.valid.json").write_text(
            json.dumps({"schema_version": "0.2.0"}), encoding="utf-8"
        )

        monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(mod, "PLUGIN_JSON", plugin_dir / "plugin.json")
        monkeypatch.setattr(
            mod, "MARKETPLACE_JSON", plugin_dir / "marketplace.json"
        )
        monkeypatch.setattr(mod, "SCHEMA_EXAMPLES_DIR", examples)

        # Simulate: mainline exists, merge-base exists, source changed,
        # mainline version is same as current (so bump is required but
        # hasn't happened).
        monkeypatch.setattr(mod, "find_mainline", lambda: "origin/main")
        monkeypatch.setattr(
            mod, "_git", lambda *a, **kw: "deadbeef" if a and a[0] == "merge-base" else ""
        )
        monkeypatch.setattr(
            mod, "source_changed", lambda base, head, source_dirs: True
        )
        monkeypatch.setattr(mod, "version_at_revision", lambda rev: "0.2.0")

        exit_code = mod.main([])
        assert exit_code == 1


class TestMarketplaceLookup:
    def test_finds_plugin_by_name_even_if_first(self, monkeypatch, tmp_path):
        src = REPO_ROOT / ".claude-plugin"
        dst = tmp_path / ".claude-plugin"
        dst.mkdir()
        (dst / "plugin.json").write_text(
            (src / "plugin.json").read_text(encoding="utf-8"), encoding="utf-8"
        )

        # Marketplace with a decoy entry first, then the real jewzaam-reviews entry.
        marketplace = json.loads((src / "marketplace.json").read_text(encoding="utf-8"))
        real = marketplace["plugins"][0]
        marketplace["plugins"] = [
            {"name": "other", "version": "9.9.9"},
            real,
        ]
        (dst / "marketplace.json").write_text(
            json.dumps(marketplace, indent=2), encoding="utf-8"
        )

        import importlib.util

        spec = importlib.util.spec_from_file_location("vcheck", SCRIPT)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        monkeypatch.setattr(mod, "MARKETPLACE_JSON", dst / "marketplace.json")

        got = mod.read_marketplace_version()
        assert got == real["version"]
