# CLAUDE.md

## Project

This repository contains a single Claude Code skill (`SKILL.md`) for processing PR review feedback. It is not a code project — there is no build system, no tests, no dependencies beyond `gh` CLI.

## Editing SKILL.md

- The skill is invoked explicitly via `/update-pr` — it does not auto-trigger
- All GitHub interactions are read-only — the skill never pushes, comments, or resolves threads
- Local code changes are delegated to the `apply-review` skill, not applied directly
- Finding IDs use prefixes: `I` (important), `S` (suggestion), `C` (clarification)
- Every user-facing gate uses `AskUserQuestion` — plain text questions get missed

## Key constraints

- No new findings beyond what PR reviewers raised — the skill organizes feedback, it does not perform independent code review
- Resolved PR threads are always filtered out before the interactive walkthrough
- Comment numbering in traceability tables is document-local (starts at 1 per reviewer), not GitHub comment IDs

## Related skills

- [apply-review](https://github.com/jewzaam/claude-skill-apply-review) — implements findings from `Review-*.md` files as isolated, tested commits. This skill hands off accepted local edits to apply-review via scoped finding IDs
