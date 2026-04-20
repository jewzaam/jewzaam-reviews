.PHONY: check test version-check

check: test version-check  ## Run all checks

test:  ## Run pytest across plugin + skills
	python -m pytest

version-check:  ## Validate semver: format, sources match, version bumped vs mainline
	@python scripts/version-check.py
