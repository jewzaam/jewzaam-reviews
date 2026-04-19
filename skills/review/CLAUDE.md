# claude-skill-review

This repo contains a Claude Code skill (`SKILL.md`) that performs parallel multi-agent codebase reviews via a JSON-native pipeline (1 + 7×N agents per run, with schema-validated boundaries and ≤8-finding validation batches).

## Repo structure

- `SKILL.md` — the skill definition (frontmatter + instructions)
- `schemas/` — JSON Schema 2020-12 contracts for every JSON boundary in the pipeline
- `scripts/` — bash and Python helpers (bootstrap, validator, renderer, plus the existing pre-fetch scripts)
- `tests/` — pytest tests for Python scripts and bash assertion scripts for shell scripts
- `Makefile` — `make check` / `make test` / `make format-check` / `make lint` (defaults to `check`)
- `pyproject.toml` — declares dev deps (pytest, jsonschema, black, flake8); no installable package
- `LICENSE` — GPL-3.0
- `README.md` — user-facing documentation

## Working in this repo

- `SKILL.md` is the central skill definition; supporting JSON schemas and helper scripts live under `schemas/` and `scripts/`.
- The skill is `SKILL.md` plus supporting JSON schemas (`schemas/`), Python and shell scripts (`scripts/`), and pytest tests (`tests/`). No installable package; tests run with `make test`.
- Review output files (`Review-*.json`, `Review-*.md`, `Review-*-supplementary.md`) are generated in target projects, not in this repo.
- Follow the skill's own conventions: phased analysis, numerical scoring (impact, likelihood, effort_to_fix, confidence), severity buckets and IDs (C/I/S/N) assigned only at the final render step.

## Dependencies

- **feature-dev** Claude Code plugin (`feature-dev@claude-plugins-official`) — validation agents use `subagent_type: "feature-dev:code-reviewer"` for structural read-only enforcement.
- **Python 3.12+** with `jsonschema` available — for `validate-findings.py` and `render-review.py`. Install dev deps with `make install-dev`.
