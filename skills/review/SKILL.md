---
name: review
description: Perform a scope-aware multi-agent codebase review via the script orchestrator. A selector agent picks applicable review lenses from the diff or repo shape, lens agents review in parallel, validators adversarially check critical/important findings, and deterministic scripts handle everything else. Use when the user asks to review, assess, audit, or evaluate a codebase or project. Accepts an optional PR number, a --scoring flag, and free-form guidance text.
disable-model-invocation: true
argument-hint: "[PR-number] [--scoring categorical|simple] [guidance text...]"
allowed-tools:
  - Bash(python ${CLAUDE_PLUGIN_ROOT}/orchestrator/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/orchestrator/**)
---

# Review Skill

## Purpose

Run the review orchestrator: a Python CLI that owns the whole review pipeline. Models are used only for reasoning (lens selection, lens review agents, validators) via headless agent invocations; everything deterministic is script. The main agent's job here is just to launch the CLI and relay its output.

## Process

### 1. Parse Arguments

From `$ARGUMENTS`:

- A leading all-digits token is the PR number → `--pr <N>`.
- A `--scoring categorical` or `--scoring simple` token passes through unchanged.
- A `--skip-lenses <slugs>` token passes through unchanged.
- Everything else is guidance → `--guidance "<text>"` (omit when empty).

### 2. Scoring Mode

If `--scoring` was not given, ask via AskUserQuestion:

1. **Categorical (default)** — five-dimension rubric with per-dimension justifications; deterministic severity mapping; stronger noise filtering. Higher output-token cost per finding.
2. **Simple** — direct severity + confidence; cheaper and lighter; low-confidence findings land in needs-review.

If a prior run's `.tmp-review/costs.json` exists in the project, read `total_cost_usd` and `scoring` from it and include that measured number in the option descriptions. Never invent cost numbers — cite measured ones or give none.

### 3. Lens Selection

If `--skip-lenses` was given in the arguments, skip this step. Otherwise run via foreground Bash:

```
python ${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py --select-only [--pr N] [--guidance "..."]
```

It prints the lenses the selector matched for this scope, one per line as `lens: <slug>: <rationale>`, and saves the selection so the review run does not re-run the selector.

Ask which of the MATCHED lenses to skip via AskUserQuestion, built dynamically from that output — this skill does not know the lens roster; the orchestrator owns it:

- multiSelect question(s), header "Skip lenses"; one option per reported lens, label = slug, description = its rationale.
- A question holds at most 4 options — with more than 4 matched lenses, split across questions (4 per question) in a SINGLE AskUserQuestion call.
- Default is skipping none: submitting with nothing selected runs every matched lens.

Selected slugs become `--skip-lenses <comma-separated>`. Nothing selected → omit the flag. If the session is non-interactive and the question cannot be asked, proceed with no skips.

### 4. Start the Review (detached)

Run this via foreground Bash from the project root, EXACTLY ONCE. The path below is pre-substituted with the plugin root and matches this skill's allowed-tools; never rewrite it into another form:

```
python ${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py --detach [--pr N] [--scoring MODE] [--skip-lenses slugs] [--guidance "..."]
```

The bracketed flags come from Step 1's parse of `$ARGUMENTS`: include `--pr` only when a leading PR number was given, `--scoring` from the argument or Step 2's answer, `--skip-lenses` from the argument or Step 3's answer (omit when none), `--guidance` only when non-empty. A relative `python orchestrator/cli.py ...` will be permission-denied — the absolute form above is the only allowed one.

It returns immediately; the review runs as a detached process that survives this session.

### 5. Wait For Completion

Run this via foreground Bash, repeatedly:

```
python ${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py --wait
```

- Exit code 3 means still running (each call blocks up to ~100 s). Run the SAME command again. Reviews commonly take 10-30 minutes — 10 or more repeats is normal.
- Any other exit code means done; the command has printed the run's final output.
- Do not run any other commands against the project between waits, and do not end your turn while the exit code is 3.

### 6. Relay Results

The run writes three files at the project root: `Findings-review[-<scope>].json` (structured findings), `.md` (critical/important detail), and `-supplementary.md` (suggestions, needs-review, decomposition, cross-cutting observations).

Relay the final `--wait` output verbatim: severity counts, output filenames, and the measured per-stage cost table. If it reports a non-zero finish, show that output and stop — do not attempt to reconstruct findings yourself.

## Critical Rules

- Never write or edit `Findings-*` files — the renderer script owns them.
- Never re-run pipeline stage scripts by hand; the orchestrator sequences them.
- The orchestrator's cost table is measured spend from the agent backend. Report it as-is.
