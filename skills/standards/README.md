# claude-skill-standards

A Claude Code skill that audits a repository against the user's personal coding standards library at `~/source/standards/`. It is the standards-focused counterpart to [claude-skill-review](https://github.com/jewzaam/claude-skill-review): `/review` assesses a codebase against its own conventions, while `/standards` assesses a codebase against the external standards library.

## Overview

When invoked in a user-owned repo, the skill:

1. Parses the `## ` section headers of `~/source/standards/CLAUDE.md` to derive standards subdomains (Common, Python, Tkinter UI, CLI, Build and CI/CD, Claude Code — current set, auto-updating as the standards repo grows).
2. Launches one parallel agent per subdomain. Each agent reads every standards file in its subdomain, decides per-standard applicability, and reports gaps for applicable standards.
3. Consolidates findings into `Review-<project>-standards.md` (Critical/Important/Suggestions in one file) plus a `-supplementary.md` with per-subdomain detail and non-applicable standards.
4. Spawns per-severity validation agents that re-read cited sources and remove or downgrade any findings that don't hold up.
5. Leaves the review document in a format that `/apply-review` can consume to iteratively fix findings.

The skill is **read-only** — it never modifies source code, installs dependencies, or runs the program.

## Scope

Only runs on user-owned repos. Ownership is determined by the origin remote owner: GitHub `jewzaam` or GitLab `nmalik`. In any other repo the skill prints `NOT_APPLICABLE: ...` and exits without writing review files. This scope is intentional — the standards library encodes personal preferences that are not meaningful to impose on third-party code. For general codebase review use [claude-skill-review](https://github.com/jewzaam/claude-skill-review).

## Dependencies

- **feature-dev plugin** — subdomain agents and validators use `subagent_type: "feature-dev:code-reviewer"` for structural read-only tool restriction. Install via `/plugin install feature-dev@claude-plugins-official`.
- **~/source/standards/** — clone of [jewzaam/standards](https://github.com/jewzaam/standards) at that path. The skill parses `CLAUDE.md` and reads linked files by absolute path.

## Installation

Clone the repo into your Claude Code skills directory:

```bash
cd ~/.claude/skills/
git clone git@github.com:jewzaam/claude-skill-standards.git standards
```

## Usage

```
/standards
```

No arguments. The skill audits the current repo against every applicable standard in the library.

## Output

- `Review-<project>-standards.md` — TL;DR, applicability matrix, Critical/Important/Suggestions findings, recommendations, validation summary.
- `Review-<project>-standards-supplementary.md` — strengths, per-subdomain notes, non-applicable standards with reasons.

## Follow-up

```
/apply-review Review-<project>-standards.md
```

Applies the findings as iterative, committed fixes. See [claude-skill-apply-review](https://github.com/jewzaam/claude-skill-apply-review).

## License

Apache 2.0. See [LICENSE](LICENSE).
