# apply-review

A Claude Code skill that takes a `Review-*.md` file and systematically applies its findings as code changes.

## What It Does

When you run the [code review skill](https://github.com/jewzaam/claude-skill-review), it produces a `Review-*.md` file with structured findings (bugs, style issues, refactors, etc.). This skill reads that file and works through each finding one at a time:

1. Implements the fix
2. Validates with tests/linting
3. Hands off for your review before committing

Each finding becomes an isolated, tested commit with a targeted message referencing the original review finding ID.

## Usage

```
/apply-review
/apply-review Review-my-feature.md
/apply-review Review-my-feature.md C0 I2 S3
```

If no argument is given, the skill searches for `Review-*.md` files at the project root. You can optionally specify finding IDs to apply only a subset — finding IDs use prefixes `C` (critical), `I` (important), and `S` (suggestion).

## Workflow Options

At each handoff, you choose how to proceed:

- **Yes, commit** — stage and commit this finding, move to the next
- **Need changes** — provide feedback, the fix is revised and re-validated
- **Skip commits, apply all remaining** — enter batch mode: all remaining findings are implemented and validated but left uncommitted in the working tree for you to handle

## Requirements

- A `Review-*.md` file produced by [claude-skill-review](https://github.com/jewzaam/claude-skill-review)
- Make targets for validation (e.g., `make test-unit`, `make lint`, `make typecheck`, `make format` — the skill checks the Makefile for available targets)

## License

Apache 2.0 — see [LICENSE](LICENSE).
