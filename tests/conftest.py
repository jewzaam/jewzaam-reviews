"""Shared pytest fixtures for plugin-root tests."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_SCHEMAS_DIR = REPO_ROOT / "schemas"
SHARED_EXAMPLES_DIR = SHARED_SCHEMAS_DIR / "examples"


@pytest.fixture
def shared_schemas_dir() -> Path:
    return SHARED_SCHEMAS_DIR


@pytest.fixture
def shared_examples_dir() -> Path:
    return SHARED_EXAMPLES_DIR
