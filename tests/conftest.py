"""Pytest fixtures for plugin-root tests.

Naming convention (mirrors `skills/*/tests/conftest.py`): bare `SCHEMAS_DIR`
and `EXAMPLES_DIR` constants with matching lowercase fixture functions. Each
conftest is scoped to its own test tree so the same names don't collide.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
EXAMPLES_DIR = SCHEMAS_DIR / "examples"


@pytest.fixture
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR
