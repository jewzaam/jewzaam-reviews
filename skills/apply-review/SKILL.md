---
name: apply-review
description: Apply findings from a Findings-*.json file as iterative, committed fixes.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, AskUserQuestion, Agent, TaskCreate, TaskUpdate, TaskGet, TaskList
argument-hint: "[Findings-file.json] [C0 I1 S2...]"
---

# Apply Review

## Pre-Fetch

### Workspace Bootstrap (auto-executed)

Wipes and recreates `.tmp-apply-review/` at the project root with a `.gitignore` of `*`. The final step writes a pre-render JSON here for `render-apply-report.py`.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh .tmp-apply-review`

### Shared Handoff Contract (auto-injected)

!`cat ${CLAUDE_PLUGIN_ROOT}/resources/handoff-contract.md`

## Purpose

Take a `Findings-*.json` file produced by any producer skill in this plugin (`/review`, `/standards`, `/c4-reverse-engineer`, `/update-pr`) and systematically apply its findings as code changes — one finding at a time, with test validation and user review before each commit. Output a `Report-apply-review.json` summarizing what was applied.

The input is the authoritative JSON handoff (validated against `${CLAUDE_PLUGIN_ROOT}/schemas/findings.schema.json`). The companion `.md` files are human-readable views — this skill does not parse them.

The key value is discipline: each finding becomes an isolated, tested, committed change with a targeted commit message. The user controls staging and can reject or modify any change before it lands.

## Finding the Findings File

1. If an argument is provided, use it as the findings file path. Accept `.json` only — if given `.md`, look for a sibling `.json` with the same basename and use that; if none exists, stop and tell the user the producer skill must re-run.
2. If no argument, search for `Findings-*.json` files at the project root.
3. If multiple findings files exist, use AskUserQuestion to let the user pick.
4. If none exist, tell the user and stop.

## Process

### 0. Establish a Clean Baseline

Before touching any code, verify the project's checks pass cleanly. Check the Makefile for available validation targets (e.g., `make test-unit`, `make lint`, `make typecheck`, `make format`) and run whichever exist. Capture the results.

If any check fails, use AskUserQuestion to present the failures and ask:
- "Fix first" — resolve the pre-existing failures before starting review work (preferred — a clean baseline makes it obvious when a review fix introduces a regression)
- "Proceed anyway" — note the pre-existing failures and continue, accepting that validation will be noisier

A clean starting state is strongly preferred. When pre-existing failures exist and the user chooses to proceed, record the exact failure signatures (test names, lint rules, error messages) so they can be filtered out during per-finding validation in Step 3b.

### 1. Parse the Findings

Read the `Findings-*.json` file and iterate `findings[]`. Each finding is a structured object with (at minimum) the shared schema's base fields:
- `id` — prefix `C` / `I` / `S` / `N` followed by a zero-indexed sequence number per bucket (e.g., `C0`, `I3`, `S1`, `N0`)
- `severity` — `critical | important | suggestion | needs-review`
- `title` — short summary
- `locations[]` — array of `{path, line, role?}` objects
- `issue`, `why_it_matters`, `suggested_fix` — prose fields
- `content_hash` — stable identifier; useful for log/commit references

Source-specific extras (`concern_slug` for review, `subdomain` for standards, `artifact`/`verdict`/`spec_says`/`code_says`/`evidence` for c4-validation) are present when the producer adds them — use them for context but don't require them.

**Read the top-level `issues[]` array** before beginning. These are meta-issues from the producer skill (sub-agent failures, permission denials, validation rejections). If an issue with `severity: "error"` is present, surface it to the user and confirm they still want to proceed — the review may be incomplete.

**Skip `needs-review` findings.** By convention, `N*` findings are low-confidence and belong to manual triage, not automatic application.

**Scoped finding IDs:** If the user provided specific finding IDs as arguments (e.g., `/apply-review Findings-update-pr-123.json C0 I2 S3`), only process those findings. Skip all others — they are out of scope for this run. This is how the `update-pr` skill delegates accepted local edits: it produces a `Findings-update-pr-<number>.json` with the full traceability, then hands off only the finding IDs that need code changes.

Sort findings by implementation order — dependencies and risk:
1. Smallest/most isolated changes first (one-line fixes, no test changes)
2. Changes that modify behavior or APIs next
3. Structural refactors last (file moves, import rewrites)

Group related findings that must be applied together (e.g., if fixing a module structure also requires updating exports, those go in one step).

### 2. Create Tasks

Create a task for each finding (or group of related findings) using TaskCreate. This gives the user visibility into progress.

### 3. Iterate Through Findings

For each finding, follow this exact cycle:

#### 3a. Implement the Fix

- Mark the task as `in_progress`
- Read the affected source files before editing
- Make the code change described in the review
- If the fix changes behavior, update affected tests to match
- If the fix changes structure (moves files, renames modules), update all import references — use Grep to find every occurrence before editing

#### 3b. Validate

Run the project's test suite using make targets. Prefer the most targeted test command that covers the changed code. If it fails:
- Read the failure output
- Compare against the baseline from Step 0 — if these are the same pre-existing failures the user chose to proceed past, they're expected
- If the failure is new (not in the baseline), fix it before proceeding — this is a regression from the current change
- Re-run until the only failures are the pre-existing baseline ones (or none, if the baseline was clean)

#### 3c. Hand Off for Review and Commit

Use AskUserQuestion to present a single decision point. The question should include:
- Which finding was applied (by ID and title)
- Which files changed (brief summary)
- Test results (pass count)
- A prompt to stage the files and reply: "Stage the changed files and reply **Commit** when ready, **Need changes** if something's wrong, or **Skip commits** to apply all remaining without committing."

This is one question, one interaction. "Commit" means the user has already reviewed and staged — proceed directly to committing. No follow-up confirmation.

If the user says "Need changes", wait for their feedback, apply it, re-validate, and ask again (same single-question format).

If the user says "Skip commits, apply all remaining" (or equivalent), enter **batch mode**:
- Skip steps 3c–3d for all remaining findings (no handoff questions, no commits)
- Continue implementing and validating each remaining finding (steps 3a–3b), marking tasks complete as you go
- At the end, all changes are in the working tree, uncommitted — the user handles staging and committing on their own terms
- Still run step 4 (final verification) when done

#### 3d. Commit

The user has staged the files. Commit immediately with a targeted message:

- **Format**: Conventional commits (`fix(scope):`, `feat(scope):`, `refactor(scope):`)
- **Title**: Describes what changed, under 80 characters
- **Body**: Why the change was needed (reference the review finding ID)
- **Attribution**: `Assisted-by: Claude Code (<model-name>)` trailer
- Use the review ID (e.g., `Review: I3`) in the body so the commit links back to the finding

```bash
git commit -m "$(cat <<'EOF'
fix(scope): short description of what changed

Why this change was needed, referencing the review finding.

Review: I3

Assisted-by: Claude Code (Claude Opus 4.6)
EOF
)"
```

#### 3e. Mark Complete and Continue

- Mark the task as `completed`
- Move to the next finding

### 4. Final Verification

After all findings are applied, re-run all available validation targets from the Makefile (the same set used in Step 0). Report the results. If any check fails and it's not pre-existing, investigate and fix before declaring done.

### 5. Emit Apply Report

After verification, record what was applied by invoking the apply-report renderer:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/apply-review/scripts/render-apply-report.py \
  --input .tmp-apply-review/pre-render.json \
  --out-dir <project root> \
  --project-name <project name from the consumed review>
```

Before invoking, write `.tmp-apply-review/pre-render.json` with:

```json
{
  "project": {"name": "<project-name>"},
  "applied": [
    {"finding_id": "C0", "outcome": "applied|skipped|failed", "detail": "<short note>"}
  ],
  "issues": [
    {"severity": "error|warning", "kind": "<from shared schema>", "message": "..."}
  ]
}
```

The script validates against the shared schema (`source: "apply-review"`, `findings: []`, required `applied[]`) and writes `Report-apply-review.json` at `--out-dir`. It does **not** emit markdown — apply-review is a consumer skill producing an action report, not a review document.

Exits non-zero on validation failure; no file is written in that case.

## Critical Rules

- **One finding per commit** — keeps changes reviewable and revertable
- **Never run `git add`** — the user controls staging; hooks block it
- **Never run `git push`** — the user controls when to push
- **Never change branches** — work on the current branch
- **Always validate before handoff** — don't present broken changes to the user
- **Always use AskUserQuestion at handoff** — the user has hooks that surface questions; plain text gets missed
- **Read before editing** — always read files before making changes
- **Use make targets** — check the Makefile for available targets and prefer them over raw commands

## Edge Cases

- **Pre-existing failures**: Handled by Step 0. If the user chose "Proceed anyway", compare every failure against the recorded baseline signatures. New failures are regressions; baseline failures are expected noise.
- **Finding requires investigation**: If the review says "investigate X before fixing", do the investigation and report findings before making changes. Use AskUserQuestion to confirm the approach.
- **Finding is invalid**: If investigation reveals a finding doesn't apply (e.g., the code has already been fixed, or the finding was based on incorrect assumptions), use AskUserQuestion to tell the user and skip it.
