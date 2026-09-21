---
name: validate-supplementary
description: Adversarially validate the review findings the last run left unchallenged — the suggestion and needs-review findings in Findings-review-supplementary.md. Reuses the previous run's intermediate state instead of reviewing again. Use when the user asks to validate, challenge, verify, or check the supplementary findings, or to finish validating a review.
disable-model-invocation: true
argument-hint: "[--validate-buckets buckets]"
---

# Validate Supplementary Skill

## Purpose

A normal review validates only its critical and important findings. Everything
else lands in `Findings-review[-<scope>]-supplementary.md` with nothing having
challenged it. This skill runs the validators over those leftovers and
re-renders the findings files in place.

It does **not** review again. Lens agents are not deterministic, so a second
review produces a different finding set — the supplementary findings the user
just read might not appear in it at all. This validates *those* findings, by
reusing the previous run's `.tmp-review/10-merged/`.

**That directory is wiped by the next review.** Once it is gone, these
findings cannot be recovered and the CLI says so rather than quietly starting
a full review.

This skill runs under both Claude Code and Codex. Set `<HARNESS>` from the
host: `codex` under Codex, `claude` under Claude Code.

## Orchestrator path

`<ORCH>` is `orchestrator/cli.py`, two directories above this `SKILL.md` — this
file is at `<plugin-root>/skills/validate-supplementary/SKILL.md`, so the CLI is
at `<plugin-root>/orchestrator/cli.py`.

Under Claude Code that resolves via `${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py`.
Under Codex that variable is not set for skill bodies — use the absolute path
built from this file's own location, which the host tells you when it lists the
skill. `<ORCH>` must be absolute; a bare `python orchestrator/cli.py` runs from
the project root and will not find it.

## Process

### 1. Parse Arguments

Almost always empty. The one token that passes through is
`--validate-buckets <buckets>`, which narrows the run to those severity buckets
instead of every finding without a verdict. Ignore anything else — this skill
takes no PR number, no guidance and no scoring, because it reuses the scope the
previous run saved.

### 2. Start

Run this via foreground Bash from the project root, EXACTLY ONCE:

```
python <ORCH> --harness <HARNESS> --detach --resume-validation [--validate-buckets buckets]
```

It returns immediately; the validators run as a detached process that survives
this session.

Exit code 2 with a message about a missing `.tmp-review/10-merged/` means the
findings from that run are gone — a later review wiped them. Report that and
stop. Do not start a full review to work around it; that is a different,
far more expensive operation the user did not ask for.

Exit code 2 about `--scoring simple` means that run used the simple path, which
does not keep the stage directories this resumes from. Report it and stop.

### 3. Wait For Completion

Run this EXACTLY ONCE, via **background** Bash (`run_in_background: true`) —
never foreground, never repeatedly:

```
python <ORCH> --harness <HARNESS> --wait --wait-timeout-s 3600
```

A backgrounded command issues no model requests while it runs; the harness
re-invokes this session when it exits. **Do not poll** — repeating `--wait` on
its short default timeout spends a main-session request every couple of minutes
and buys nothing the wake-up does not.

On a host that cannot both background a command and wake the session when it
exits, run the same command in the **foreground** with the full
`--wait-timeout-s 3600`, and re-run it on exit code 3.

### 4. Relay Results

The run rewrites `Findings-review[-<scope>].{json,md,-supplementary.md}` in
place. Findings the validators remove disappear from them; rescored findings
move between severity buckets, so a finding can leave the supplementary file
for the main one.

Relay the final `--wait` output verbatim: severity counts, filenames, the
run-report step table, the operational issue list, and the cost plus
normalized-token tables. The cost table covers this validation pass only — the
original review's spend is not re-reported here.

## Critical Rules

- Never write or edit `Findings-*` files — the renderer script owns them.
- Never re-run pipeline stage scripts by hand; the orchestrator sequences them.
- Never fall back to a full review when the resume fails. Report and stop.
