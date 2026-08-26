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

### 2. Lens Selection

If `--skip-lenses` was given in the arguments, skip this step. Otherwise run via foreground Bash:

```
python ${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py --select-only [--pr N] [--guidance "..."]
```

It prints the lenses the selector matched for this scope, one per line as `lens: <slug>: <rationale>`, and saves the selection so the review run does not re-run the selector.

The selector does not depend on the scoring mode. Ask the user NOTHING here — its output is needed to build the lens question, and every question is asked together in Step 3.

### 3. Ask Everything At Once

Exactly ONE AskUserQuestion call, carrying every decision still unanswered after Step 1's parse. Never two calls — the user answers one prompt per review, not one per decision. If neither question below applies, ask nothing and go to Step 4.

**Scoring question** — include only when `--scoring` was not in `$ARGUMENTS`. Header "Scoring", two options:

1. **Categorical (default)** — five-dimension rubric with per-dimension justifications; deterministic severity mapping; stronger noise filtering. Higher output-token cost per finding.
2. **Simple** — direct severity + confidence; cheaper and lighter; low-confidence findings land in needs-review.

If a prior run's `.tmp-review/costs.json` exists in the project, read `total_cost_usd` and `scoring` from it and include that measured number in the option descriptions. Never invent cost numbers — cite measured ones or give none.

**Skip-lenses question(s)** — include only when Step 2 ran. Built dynamically from its output; this skill does not know the lens roster, the orchestrator owns it:

- multiSelect, header "Skip lenses"; one option per lens Step 2 reported, label = slug, description = its rationale.
- A question holds at most 4 options — with more than 4 matched lenses, split across additional questions (4 per question) inside the same call. The call holds at most 4 questions total, so use at most 3 for lenses when the scoring question is also present.
- Default is skipping none: submitting with nothing selected runs every matched lens.

Selected slugs become `--skip-lenses <comma-separated>`. Nothing selected → omit the flag. If the session is non-interactive and the call cannot be made, use `categorical` with no skips.

### 4. Start the Review (detached)

Run this via foreground Bash from the project root, EXACTLY ONCE. The path below is pre-substituted with the plugin root and matches this skill's allowed-tools; never rewrite it into another form:

```
python ${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py --detach [--pr N] [--scoring MODE] [--skip-lenses slugs] [--guidance "..."]
```

The bracketed flags come from Step 1's parse of `$ARGUMENTS`: include `--pr` only when a leading PR number was given, `--scoring` and `--skip-lenses` from the argument or Step 3's answers (omit `--skip-lenses` when none), `--guidance` only when non-empty. A relative `python orchestrator/cli.py ...` will be permission-denied — the absolute form above is the only allowed one.

It returns immediately; the review runs as a detached process that survives this session.

### 5. Wait For Completion

Run this EXACTLY ONCE, via **background** Bash (`run_in_background: true`) — never foreground, never repeatedly:

```
python ${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py --wait --wait-timeout-s 3600
```

A backgrounded command issues no model requests while it runs; the harness re-invokes this session when it exits. So the entire 10-30 minute review costs the orchestrating session nothing.

**Do not poll.** Repeating `--wait` on its ~100 s default timeout spends a main-session request every couple of minutes for the whole run, and each one re-sends a conversation that grew by the previous poll — the cost climbs the longer the review takes. That loop is the single largest orchestration expense there is, and it buys nothing the wake-up does not.

- The command prints the run's final output when it wakes you.
- Exit code 3 means the run is still going after a full hour. Re-run the same background command; do not fall back to foreground polling.
- Do not run other commands against the project while it is running.

**If the user asks what the review is doing mid-run**, read `.tmp-review/agent-logs/<lens>-<dimension>.log` — the CLI's own debug log per agent, written live (`agent-trace.jsonl` is only appended once an agent finishes, so it is empty for agents still working). Report what you see and stop there. Do not kill, restart, or otherwise act on a log: a quiet log does not mean a stuck agent, it looks identical to one inside a long tool call. Agents are capped on spend, not time, so a slow one is not a runaway.

### 6. Relay Results

The run writes three files at the project root: `Findings-review[-<scope>].json` (structured findings), `.md` (critical/important detail, plus a concern-by-severity table linking the rest), and `-supplementary.md` (every finding grouped by concern then severity, decomposition, cross-cutting observations). Critical and important findings appear in both markdown files by design — the main file is the severity read, the supplementary is the per-concern read.

Relay the final `--wait` output verbatim: severity counts, output filenames, and the measured per-stage/model cost table. If it reports a non-zero finish, show that output and stop — do not attempt to reconstruct findings yourself.

## Critical Rules

- Never write or edit `Findings-*` files — the renderer script owns them.
- Never re-run pipeline stage scripts by hand; the orchestrator sequences them.
- The orchestrator's cost table is measured spend from the agent backend. Report it as-is.
