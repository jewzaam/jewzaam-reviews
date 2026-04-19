# jewzaam-reviews

Claude Code plugin bundling the review pipeline skills. Distributed as a marketplace plugin; not symlinked from `~/.claude/skills/`.

## Structure

```
.claude-plugin/
  plugin.json        # Plugin metadata (name, version, license)
  marketplace.json   # Marketplace listing
LICENSE              # Apache-2.0
README.md            # User-facing docs
skills/
  <skill-name>/
    SKILL.md         # Required entry point
    scripts/, schemas/, references/, docs/  # Optional supporting files
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

## Adding a Skill

1. Create `skills/<name>/SKILL.md` with proper frontmatter (`name`, `description`).
2. Add supporting files under the skill directory (`scripts/`, `schemas/`, etc.).
3. Reference internal files via `${CLAUDE_PLUGIN_ROOT}/skills/<name>/...`.
4. Update `README.md` skill table.
5. Bump `version` in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (SemVer).

## Versioning

SemVer per `~/source/standards/common/versioning.md`. The two `version` fields in `plugin.json` and `marketplace.json` must stay in sync.

## License

Apache-2.0 for everything in this repo.
