.PHONY: check test version-check check-resolved-schemas resolve-schemas version-bump-patch version-bump-minor version-bump-major help

check: test version-check check-resolved-schemas  ## Run all checks

test:  ## Run pytest across plugin + skills
	python -m pytest

version-check:  ## Validate semver: format, sources match, version bumped vs mainline
	@python scripts/version-check.py

resolve-schemas:  ## Regenerate resolved (LLM-friendly) schemas from source schemas
	@python scripts/resolve_schema.py

check-resolved-schemas:  ## Verify resolved schemas are up-to-date
	@python scripts/check-resolved-schemas.py

version-bump-patch:  ## Bump patch version (i.e. 0.2.8 → 0.2.9)
	@python scripts/version-bump.py patch

version-bump-minor:  ## Bump minor version (i.e. 0.2.8 → 0.3.0)
	@python scripts/version-bump.py minor

version-bump-major:  ## Bump major version (i.e. 0.2.8 → 1.0.0)
	@python scripts/version-bump.py major

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'
