"""Tests for skills/c4-reverse-engineer/scripts/find_platform_conditionals.py."""

import importlib.util
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "find_platform_conditionals.py"


def _load():
    spec = importlib.util.spec_from_file_location("find_platform_conditionals", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScanFile:
    """scan_file is deliberately comment-blind and extension-agnostic —
    the extension filter is applied upstream in walk(). These tests pin
    that contract so refactoring doesn't silently shift responsibility."""

    def test_sys_platform_detected(self, tmp_path):
        mod = _load()
        f = tmp_path / "a.py"
        f.write_text("if sys.platform == 'win32':\n    pass\n", encoding="utf-8")
        hits = mod.scan_file(f)
        assert any("sys.platform" in label for label, _, _ in hits)

    def test_os_name_detected(self, tmp_path):
        mod = _load()
        f = tmp_path / "a.py"
        f.write_text("if os.name == 'nt':\n    pass\n", encoding="utf-8")
        hits = mod.scan_file(f)
        assert any("os.name" in label for label, _, _ in hits)

    def test_multiple_patterns_in_file_all_reported(self, tmp_path):
        # A file mixing several conditional kinds — each distinct match
        # should produce at least one hit.
        mod = _load()
        f = tmp_path / "a.py"
        f.write_text(
            "if sys.platform == 'win32': pass\n"
            "if os.name == 'nt': pass\n"
            "if IS_WINDOWS: pass\n",
            encoding="utf-8",
        )
        hits = mod.scan_file(f)
        labels = {label for label, _, _ in hits}
        assert len(labels) >= 3

    def test_no_platform_patterns_no_hits(self, tmp_path):
        mod = _load()
        f = tmp_path / "a.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")
        assert mod.scan_file(f) == []


class TestWalk:
    def test_skip_dirs_excluded(self, tmp_path):
        mod = _load()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text(
            "if sys.platform == 'win32':\n    pass\n", encoding="utf-8"
        )
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "b.py").write_text(
            "if sys.platform == 'darwin':\n    pass\n", encoding="utf-8"
        )
        results = list(mod.walk(tmp_path))
        paths = [str(p) for p in results]
        assert any("src" in p for p in paths)
        assert not any("node_modules" in p for p in paths)
