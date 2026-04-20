# jewzaam-reviews

Claude Code plugin bundling the review pipeline skills. Distributed as a marketplace plugin; not symlinked from `~/.claude/skills/`.

## Structure

```
.claude-plugin/
  plugin.json        # Plugin metadata (name, version, license)
  marketplace.json   # Marketplace listing
LICENSE              # Apache-2.0
README.md            # User-facing docs
Makefile             # `make test` runs pytest across the plugin
pyproject.toml       # pytest configuration
schemas/
  findings.schema.json   # Shared cross-skill handoff schema
  examples/              # Valid + invalid fixtures per source
scripts/
  version-check.py       # Semver + sources-match + bump-vs-mainline check
tests/
  test_findings_schema.py  # Validation tests for the shared schema
skills/
  <skill-name>/
    SKILL.md         # Required entry point
    scripts/         # Render scripts, helper scripts
    schemas/         # Skill-internal JSON schemas (not the shared handoff)
    references/, docs/  # Optional supporting files
    tests/           # pytest tree for this skill's scripts
```

## Plugin Path Resolution

**Critical**: When skills run inside a plugin, they are NOT at `~/.claude/skills/<name>/`. They live under the plugin install cache. Skill content must use `${CLAUDE_PLUGIN_ROOT}` to reference its own files, not absolute `~/.claude/skills/...` paths.

- Wrong: `python ~/.claude/skills/review/scripts/validate-findings.py`
- Right: `python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py`

When editing any `SKILL.md`, grep for `~/.claude/skills/` references and convert them.

## Skill Sources

These skills were copied from standalone repos (now retired):
- `review` ← `claude-skill-review`
- `standards` ← `claude-skill-standards`
- `update-pr` ← `claude-skill-update-pr`
- `c4-reverse-engineer` ← `claude-skill-c4-reverse-engineer`
- `apply-review` ← `claude-skill-apply-review`

This repo is the new home; do not edit the originals.

## Shared JSON Handoff

All producer skills (review, standards, update-pr, c4 validation) and the apply-review consumer exchange structured findings through `schemas/findings.schema.json` at the plugin root. This is the cross-skill contract — skill-internal schemas (e.g., `skills/review/schemas/consolidated.schema.json`) stay local to their skill.

**Invariants — non-negotiable:**

1. **Every producer validates JSON output against `schemas/findings.schema.json` before writing.** Validation lives in the render script; fail fast, non-zero exit, no half-written artifacts.
2. **Markdown is always rendered from JSON by a script — never hand-authored.** The JSON is the source of truth; `.md` files are scripted views over it. No direct `Write(Findings-*.md)` or `Write(Report-*.md)` anywhere.
3. **Every JSON carries a top-level `issues[]` array** (may be empty) — the uniform place to capture meta-issues from the run (permission denials in sub-agents, sub-agent failures, tool unavailability, schema rejection of partial inputs). Findings describe the user's code; issues describe the skill's own operation.

Render scripts per skill:

| Skill | Render script | Source value |
|---|---|---|
| review | `skills/review/scripts/render-review.py` | `review` |
| standards | `skills/standards/scripts/render-standards.py` | `standards` |
| c4-reverse-engineer | `skills/c4-reverse-engineer/scripts/render-c4-validation.py` | `c4-validation` |
| update-pr | `skills/update-pr/scripts/render-update-pr.py` | `review` (with `pr_comment` on findings) |
| apply-review | `skills/apply-review/scripts/render-apply-report.py` | `apply-review` |

## Adding a Skill

1. Create `skills/<name>/SKILL.md` with proper frontmatter (`name`, `description`).
2. Add supporting files under the skill directory (`scripts/`, `schemas/`, `tests/`).
3. Reference internal files via `${CLAUDE_PLUGIN_ROOT}/skills/<name>/...`.
4. **If the new skill produces findings or an action report**, write a render script that (a) builds the shared envelope, (b) validates against `schemas/findings.schema.json` before writing, (c) emits both JSON and any markdown view. Markdown must come from the JSON — never hand-authored.
5. Add pytest coverage under `skills/<name>/tests/` (`make test` auto-discovers it).
6. Update `README.md` skill table.
7. Bump `version` in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (SemVer).

## Versioning

SemVer per `~/source/standards/common/versioning.md`. The two `version` fields in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` must stay in sync.

Enforcement: `make version-check` validates that

1. `plugin.json` version matches official semver
2. `plugin.json` and `marketplace.json` versions match
3. When files in `schemas/` or `skills/` have changed vs mainline, the plugin version has been bumped

The check runs on every PR via `.github/workflows/version-check.yml`. On push to main, the workflow also creates a `vX.Y.Z` git tag if one doesn't exist.

Docs-only changes (CLAUDE.md, README.md, `.claude-plugin/` metadata other than `version`) do not require a bump — the script only looks at `schemas/` and `skills/` for bump-required detection.

## License

Apache-2.0 for everything in this repo.
