.PHONY: check test install-dev update-plugins version-check check-resolved-schemas resolve-schemas version-bump-patch version-bump-minor version-bump-major help

ifeq ($(OS),Windows_NT)
    VENV_DIR ?= .venv
    PYTHON ?= $(VENV_DIR)/Scripts/python.exe
else
    VENV_DIR ?= .venv
    PYTHON ?= $(VENV_DIR)/bin/python
endif

# Interpreter used to bootstrap the venv. CI overrides to `python` so the
# venv is pinned to the matrix Python installed by setup-python (see
# ~/source/standards/build/makefile.md).
PY_SYS ?= python3

check: test version-check check-resolved-schemas  ## Run all checks

$(PYTHON):
	$(PY_SYS) -m venv $(VENV_DIR)

install-dev: $(PYTHON)  ## Create venv and install test dependencies
	@$(PYTHON) -m pip install -q -e ".[test]"

test: install-dev  ## Run pytest across plugin + skills + orchestrator
	$(PYTHON) -m pytest

update-plugins:  ## Update installed Claude Code and Codex plugins when available
	@if command -v claude >/dev/null 2>&1; then \
		claude plugin marketplace update jewzaam-reviews-marketplace; \
		claude plugin update jewzaam-reviews@jewzaam-reviews-marketplace -y; \
	else \
		echo "claude not installed; skipped"; \
	fi
	@if command -v codex >/dev/null 2>&1; then \
		if ! codex plugin marketplace upgrade jewzaam-reviews-marketplace >/dev/null 2>&1; then \
			echo "codex marketplace refresh skipped (local or non-Git marketplace)"; \
		fi; \
		if codex plugin list 2>/dev/null | grep -q 'jewzaam-reviews@jewzaam-reviews-marketplace'; then \
			codex plugin remove jewzaam-reviews@jewzaam-reviews-marketplace; \
		fi; \
		codex plugin add jewzaam-reviews@jewzaam-reviews-marketplace; \
	else \
		echo "codex not installed; skipped"; \
	fi

version-check: install-dev  ## Validate semver: format, sources match, version bumped vs mainline
	@$(PYTHON) scripts/version-check.py

resolve-schemas: install-dev  ## Regenerate resolved (LLM-friendly) schemas from source schemas
	@$(PYTHON) scripts/resolve_schema.py

check-resolved-schemas: install-dev  ## Verify resolved schemas are up-to-date
	@$(PYTHON) scripts/check-resolved-schemas.py

version-bump-patch: install-dev  ## Bump patch version (i.e. 0.2.8 → 0.2.9)
	@$(PYTHON) scripts/version-bump.py patch

version-bump-minor: install-dev  ## Bump minor version (i.e. 0.2.8 → 0.3.0)
	@$(PYTHON) scripts/version-bump.py minor

version-bump-major: install-dev  ## Bump major version (i.e. 0.2.8 → 1.0.0)
	@$(PYTHON) scripts/version-bump.py major

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'
