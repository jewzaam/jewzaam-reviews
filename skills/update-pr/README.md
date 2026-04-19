# update-pr

A Claude Code skill for incorporating PR review feedback. Fetches PR comments from GitHub, generates a traceability document mapping comments to findings, walks through each comment one at a time with before/after context, and produces draft replies with a re-request review checklist. Accepted code changes are handed off to [apply-review](https://github.com/jewzaam/claude-skill-apply-review) for disciplined per-finding commits.

All GitHub interactions are read-only. The user posts replies and pushes commits themselves.

## What It Does

When invoked via `/update-pr <PR-number>`, this skill:

1. **Fetches** all PR comments from GitHub (top-level reviews, inline code comments, thread resolution status)
2. **Accepts** supplementary feedback from any text source (review transcripts, emails, Slack threads)
3. **Generates** `Review-PR-<number>.md` — a traceability document mapping every comment to a finding and every finding back to its source comments. Presented for user confirmation before proceeding
4. **Reviews** each unresolved comment one at a time — shows before/after context, asks for your decision (accept, reject, defer, acknowledge)
5. **Handles GitHub suggestions** via the PR UI for reviewer attribution
6. **Updates** the traceability document with resolutions, draft replies, and a re-request review checklist
7. **Hands off** accepted local edits to [apply-review](https://github.com/jewzaam/claude-skill-apply-review) for per-finding implementation, validation, and commit

## Dependencies

This skill delegates local code changes to the [apply-review](https://github.com/jewzaam/claude-skill-apply-review) skill. Install both skills for the full workflow.

The two skills share a document contract: `Review-*.md` files with a Findings section. `update-pr` produces findings from human PR comments; `apply-review` implements them as isolated, tested commits. The handoff uses scoped finding IDs (e.g., `/apply-review Review-PR-123.md I0 I2 S0`).

## Installation

Clone or check out this repository into your Claude Code skills directory:

```bash
git clone https://github.com/jewzaam/claude-skill-update-pr.git ~/.claude/skills/update-pr
```

Or symlink if you prefer to keep the repo elsewhere:

```bash
ln -s /path/to/claude-skill-update-pr ~/.claude/skills/update-pr
```

## Usage

From a branch with an open PR:

```
/update-pr 1234
```

The PR number is required. The skill will confirm which files are in scope before making changes.

## Requirements

- `gh` CLI authenticated with access to the target repository
- [apply-review](https://github.com/jewzaam/claude-skill-apply-review) skill installed (for local edit handoff)
- Claude Code with skill loading enabled
