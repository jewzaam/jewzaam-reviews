"""Tests for skills/c4-reverse-engineer/scripts/find_external_calls.py."""

import importlib.util
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "find_external_calls.py"


def _load():
    spec = importlib.util.spec_from_file_location("find_external_calls", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScanFile:
    def test_subprocess_call_detected(self, tmp_path):
        mod = _load()
        f = tmp_path / "a.py"
        f.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")
        hits = mod.scan_file(f)
        # Label format is "subprocess (Python)" etc.
        assert any("subprocess" in label.lower() for label, _, _ in hits)

    def test_comment_line_ignored(self, tmp_path):
        mod = _load()
        f = tmp_path / "a.py"
        f.write_text("# subprocess.run([...]) is a red herring here\n", encoding="utf-8")
        hits = mod.scan_file(f)
        assert hits == []

    def test_multiple_categories_per_line_all_reported(self, tmp_path):
        """After the I11 fix: one line matching two pattern groups yields two hits."""
        mod = _load()
        f = tmp_path / "a.py"
        # This line matches both python-subprocess and python-requests patterns
        f.write_text(
            "subprocess.run(requests.get('http://x').text)\n",
            encoding="utf-8",
        )
        hits = mod.scan_file(f)
        labels = {label for label, _, _ in hits}
        # The exact labels depend on pattern naming, but we should see at
        # least two distinct hits (not a single break-on-first match).
        assert len(hits) >= 2
        assert len(labels) >= 2

    def test_non_source_extension_no_hits(self, tmp_path):
        mod = _load()
        f = tmp_path / "a.txt"
        f.write_text("subprocess.run(['ls'])\n", encoding="utf-8")
        assert mod.scan_file(f) == []


class TestWalk:
    def test_skip_dirs_excluded(self, tmp_path):
        mod = _load()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text(
            "subprocess.run(['ls'])\n", encoding="utf-8"
        )
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "b.py").write_text(
            "subprocess.run(['bad'])\n", encoding="utf-8"
        )
        results = list(mod.walk(tmp_path))
        paths = [str(p) for p in results]
        assert any("src" in p for p in paths)
        assert not any("node_modules" in p for p in paths)
