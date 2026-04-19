# claude-skill-review

A Claude Code skill that performs multi-agent reviews of an entire codebase or a single PR via a JSON-native pipeline with schema-validated agent boundaries.

## Overview

The skill spawns one Build & Checks agent plus seven concern-focused review agents per dimension that the main agent identifies. For a typical full-repo review, expect 30–70 parallel agents; for small PRs, expect single-digit counts. Findings are collected as JSON, validated by separate parallel validator agents (≤8 findings each), then rendered to a structured JSON document plus two markdown files at the project root.

The seven concern axes per dimension:

- **Architecture & Design** — structure, module boundaries, design patterns
- **Implementation Quality** — correctness, error handling, type safety, resource management
- **Test Quality & Coverage** — isolation, assertion quality, missing scenarios
- **Maintainability & Standards** — naming, duplication, complexity, internal consistency
- **Security** — authn/authz, input validation, injection vectors, secret handling, supply chain
- **Documentation** — README accuracy, docstrings, examples, ADRs, install/usage instructions
- **Observability** — log quality, error context, metrics, traces, debug affordances

Each agent establishes the project's own patterns first, then assesses against that baseline — findings are grounded in the project's conventions, not abstract ideals. Each finding is scored on four numerical scales (impact, likelihood, effort_to_fix, confidence) on 0–100; severity buckets are assigned only at the final render step.

## Output

The skill writes three files at the project root for each review:

- `Review-<project-name>[-<slug>].json` — structured findings (severity buckets and IDs assigned at render time). Downstream skills (e.g., apply-review) consume this directly.
- `Review-<project-name>[-<slug>].md` — main markdown: TL;DR, build & check results, critical and important findings.
- `Review-<project-name>[-<slug>]-supplementary.md` — strengths, detailed analysis by concern, suggestions, needs-review (low-confidence) items, and the decomposition preamble showing how the work was sliced.

The slug is appended when the scope is constrained (a PR number or focus guidance).

## Severity Buckets

The renderer assigns each finding to one of four buckets based on its numerical scores:

- **Critical** (`C0..`): high impact, high likelihood, high confidence — must fix.
- **Important** (`I0..`): meaningful impact and confidence — should fix.
- **Suggestion** (`S0..`): high confidence but lower priority — nice to have.
- **Needs Review** (`N0..`): low confidence — surfaced for manual triage; downstream automation usually ignores by default.

Thresholds are configurable via `schemas/render-config.default.json`.

## Dependencies

- **feature-dev** Claude Code plugin. Validation agents use `subagent_type: "feature-dev:code-reviewer"` to enforce read-only access structurally. Concern agents use `subagent_type: "general-purpose"` (with prompt-level restrictions) because they need Write and Bash to self-validate their JSON output against the schema.
  - Install: `/plugin install feature-dev@claude-plugins-official` (requires Claude Code v2.0+).
- **Python 3.12+** with `jsonschema` available — used by `validate-findings.py` and `render-review.py`. Install dev deps with `make install-dev`.

## Installation

Clone the repo into your Claude Code skills directory:

```bash
cd ~/.claude/skills/
git clone git@github.com:jewzaam/claude-skill-review.git review
cd review && make install-dev
```

## Required permissions

The skill ships an `allowed-tools` list in `SKILL.md`'s frontmatter, but **not all Claude Code install modes propagate frontmatter permissions to sub-agents** — symlinked dev installs in particular do not. Without the rules below in `~/.claude/settings.json` (or `<project>/.claude/settings.local.json`), the skill dispatches its 1+7×N agents and they all silently fail mid-run on Write/Bash permission walls.

Copy this into your settings file:

```json
{
  "permissions": {
    "allow": [
      "Write(.tmp-review-findings/raw/**)",
      "Write(*/.tmp-review-findings/raw/**)",
      "Bash(*/.claude/skills/review/scripts/standards-check.sh)",
      "Bash(*/.claude/skills/review/scripts/pr-scope.sh *)",
      "Bash(*/.claude/skills/review/scripts/guidance.sh *)",
      "Bash(*/.claude/skills/review/scripts/bootstrap-findings-dir.sh)",
      "Bash(python */.claude/skills/review/scripts/validate-findings.py *)",
      "Bash(python */.claude/skills/review/scripts/consolidate-findings.py *)",
      "Bash(python */.claude/skills/review/scripts/batch-findings.py *)",
      "Bash(python */.claude/skills/review/scripts/render-review.py *)",
      "Read(*/.claude/skills/review/**)",
      "Read(*/claude-skill-review/**)",
      "Glob(*/.claude/skills/review/**)",
      "Glob(*/claude-skill-review/**)",
      "Grep(*/.claude/skills/review/**)",
      "Grep(*/claude-skill-review/**)"
    ]
  }
}
```

The `*/` wildcard prefix handles `~/`, `/c/Users/.../`, and Windows-native path forms uniformly (see `~/source/standards/claude-code/skills.md` for the convention). The `*/claude-skill-review/**` lines are the symlink-target form — drop them once the skill ships via the plugin marketplace.

## Usage

Invoke the skill in Claude Code:

```
/review
/review 565
/review focus on error handling and test coverage
/review 565 just the src/api/ directory, I'm worried about input validation
```

Forms:
- `/review` — full-repo review across all dimensions the main agent identifies.
- `/review <PR number>` — diff-scoped review.
- `/review <PR number> <guidance text>` — diff-scoped + free-form focus.
- `/review <guidance text>` — full-repo + free-form focus.

The skill is read-only with respect to source code — it never modifies source files, installs dependencies, or runs the user's program. Concern agents do write JSON to a `.tmp-review-findings/` workspace at the project root (gitignored) for self-validation; that workspace plus the three output files are the only writes the skill performs.

## Standards reference

For user-owned repos, the skill also checks against coding standards from `~/source/standards/` if that directory exists. Ownership is determined automatically: the skill compares the origin remote's owner against your authenticated GitHub user (`gh api user --jq '.login'`). If they match and `~/source/standards/` exists, the standards are applied.

The [jewzaam/standards](https://github.com/jewzaam/standards/) repo provides a set of language and project conventions designed for use with this skill. Contributions are welcome — if you have standards that would benefit the broader community, open a PR. To use it, clone it to `~/source/standards/`.
