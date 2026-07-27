---
name: review-supplementary
description: Validate supplementary findings (suggestion + needs-review) from a prior /review run. Run after /review when you want to validate the unvalidated supplementary findings. Requires .tmp-review/ workspace from a completed review.
disable-model-invocation: true
argument-hint: "[scope-slug]"
allowed-tools:
  # A: !-injection coverage (load-bearing)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/**)
  # B: Main-agent tools
  - Bash(ls *)
  - Bash(test -f *)
  - Bash(test -d *)
  # C: Skill file access
  - Read(${CLAUDE_SKILL_DIR}/**)
  - Glob(${CLAUDE_SKILL_DIR}/**)
  - Grep(${CLAUDE_SKILL_DIR}/**)
  # D: Validator verdict output
  - Write(./.tmp-review/15-validation/**)
  - Write(**/.tmp-review/15-validation/**)
---

# Review Supplementary Skill

## Purpose

Validate supplementary findings (suggestion and needs-review severity) from a prior `/review` run. The main review skill skips validation for these findings to reduce cost. This skill picks up where it left off — batching, validating, and re-rendering only the supplementary findings.

## Prerequisites

A completed `/review` run in the current project with `.tmp-review/10-merged/` intact. The prepare script below verifies this and aborts if missing.

## Constraints

- **Read-only analysis of source code.** Same constraints as the review skill.
- **Reuses the review skill's workspace** at `.tmp-review/`. Does not create a new workspace.
- **Reuses the review skill's pipeline scripts** — batch-findings.py, apply-verdicts.py, render-review.py. No new scripts beyond the two orchestration shells.
- **Output overwrites the prior review's output files** — `Findings-review[-<slug>].json`, `.md`, `-supplementary.md` at the project root. The updated files include validated supplementary findings alongside the already-validated critical/important findings.

## Pre-Fetch

### Prepare (auto-executed)

Validates workspace, counts existing batch outputs for offset, runs batcher with `--only-buckets suggestion,needs-review`. Exits non-zero if workspace missing or no supplementary findings exist. Outputs the list of batch input files to validate.

!`bash ${CLAUDE_SKILL_DIR}/scripts/prepare-supplementary.sh ${CLAUDE_PLUGIN_ROOT}`

### Plugin Home (auto-detected)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-plugin-home.sh ${CLAUDE_PLUGIN_ROOT}`

### Project Root (auto-detected)

!`pwd`

## Process

### 1. Dispatch Validators

Read each batch input file listed in the Prepare output above. Spawn one validator agent per batch in **parallel** in a single message:

- `model: "sonnet"`, `subagent_type: "feature-dev:code-reviewer"` (read-only structurally).
- Each validator opens the cited `finding.locations`, challenges accuracy and the five categorical dimensions, and returns a JSON object matching the `validation-output.schema.json` schema (at `${CLAUDE_PLUGIN_ROOT}/skills/review/schemas/validation-output.schema.json`) directly in its response.
- **Challenge the premise, not just the symptom.** A finding may cite real code and describe a technically accurate gap, yet be wrong because its premise is invalid — endpoint-level auth, framework validation, indirect test coverage, etc.
- **Remove positive observations.** If `suggested_fix` says "no action needed" or "continue", remove it.
- Each verdict is `"action": "confirm"`, `"action": "rescore"`, or `"action": "remove"`.
- Each verdict carries `finding_ref: {content_hash}` — copy verbatim from the input batch.

After each validator returns, write its response to `./.tmp-review/15-validation/batch-<N>-output.json` (where N matches the input batch number) and re-validate against `validation-output.schema.json`:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py ./.tmp-review/15-validation/batch-<N>-output.json
```

### 2. Finalize

Run the finalize script — it applies all verdicts (original critical/important + new supplementary), re-renders, and outputs the summary:

```
bash ${CLAUDE_PLUGIN_ROOT}/skills/review-supplementary/scripts/finalize-supplementary.sh ${CLAUDE_PLUGIN_ROOT}
```

Relay the script's output verbatim.

## Critical Rules

- **NEVER execute anything against the user's code or environment.** Static analysis only.
- **Writes restricted to `./.tmp-review/15-validation/` and the three output files at the project root.**
- **Do not re-run concern agents.** The findings already exist in `10-merged/`. This skill only validates and re-renders.
