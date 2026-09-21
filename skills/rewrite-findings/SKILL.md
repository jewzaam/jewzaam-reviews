---
name: rewrite-findings
description: Rewrite the findings of the last review — retitle a truncated or misleading heading, reword what a finding says, re-rate it, or drop one the digging disproved — then re-render Findings-review[-<scope>].{json,md}. Use when the user asks to rewrite, reframe, retitle, reword, correct, re-rate or remove review findings after discussing them.
disable-model-invocation: true
argument-hint: "[which findings, and what to change]"
---

# Rewrite Findings Skill

## Purpose

A review's framing is what makes it usable in a PR thread, and it is written
before anyone has dug into the findings. After that digging the wording is
often wrong: a title clipped mid-word, a heading that names the wrong cause, a
dimension rated from a guess the conversation has since settled, a finding the
code turned out not to support.

This skill edits the findings the last run produced in
`.tmp-review/20-findings/` and re-renders the files at the project root from
them. It reviews nothing and dispatches no agents, so it costs no agent spend
and cannot invent a finding.

**`.tmp-review/` is wiped by the next review.** Once `20-findings/` is gone the
stage files cannot be rebuilt from the rendered output by this skill, and the
CLI says so rather than starting a review nobody asked for.

**Rewrite last.** `/jewzaam-reviews:validate-supplementary` and any new review
rebuild `20-findings/` from `10-merged/`, which these edits never touch — both
discard every edit made here.

This skill runs under both Claude Code and Codex.

## Orchestrator path

`<ORCH>` is `orchestrator/cli.py`, two directories above this `SKILL.md` — this
file is at `<plugin-root>/skills/rewrite-findings/SKILL.md`, so the CLI is at
`<plugin-root>/orchestrator/cli.py`.

Under Claude Code that resolves via `${CLAUDE_PLUGIN_ROOT}/orchestrator/cli.py`.
Under Codex that variable is not set for skill bodies — use the absolute path
built from this file's own location, which the host tells you when it lists the
skill. `<ORCH>` must be absolute; a bare `python orchestrator/cli.py` runs from
the project root and will not find the CLI.

## Process

### 1. Check Both Inputs Exist

- `Findings-review[-<scope>].json` at the project root — the rendered findings,
  and the only place a finding's `id` (`C0`, `I2`, `S5`, `N1`) appears.
- `.tmp-review/20-findings/` — `_envelope.json` plus one `<content_hash>.json`
  per finding. This is what you edit.

If `20-findings/` is missing, stop and report that a later review wiped it.
Do not re-run the review, and do not hand-write the markdown instead — that
breaks the one invariant this pipeline has (markdown is always rendered from
JSON by a script).

### 2. Identify The Findings To Change

The user names findings by id. Ids live only in the rendered JSON, so read it
and map each one to its `content_hash`; the stage file is
`.tmp-review/20-findings/<content_hash>.json`.

When the user describes a finding instead of numbering it, quote the title you
matched and the id back to them in your reply, so a wrong match is visible.

### 3. Edit The Stage Files

Edit only these fields:

| Field | Rule |
|---|---|
| `title` | Under 120 characters. A heading, not a sentence — name the short symbol, not its signature or qualified path. No trailing `...` (that is the mark of the clip you are undoing). |
| `issue` | What is wrong, still supported by the cited code. |
| `why_it_matters` | The consequence. |
| `suggested_fix` | What to do. |
| the five dimensions and their `_justification` strings (categorical), or `severity` and `confidence` (simple) | Only when the conversation established the rating was wrong. The justification must say what was established, not that it was discussed. |

Leave `content_hash`, `locations`, `concern`, `concern_slug`, `dimension_name`
and `dimension_slug` exactly as they are. `content_hash` keys the finding
across every stage; rewriting it orphans the finding's verdict.

**To drop a finding**: delete its `<content_hash>.json`, and append an entry to
`issues[]` in `_envelope.json`:

```json
{
  "severity": "warning",
  "kind": "finding_removed",
  "message": "<id> \"<title>\" removed: <what established it was wrong>",
  "source_component": "rewrite"
}
```

The renderer lists it under **Pipeline Decisions**, so the report says a
finding was pulled and why. Deleting the file alone makes the finding vanish
with no record.

Rewrite what a finding *says*, never what it *found*. Every edited sentence
must still hold against the code at `locations`. If the digging showed the
finding is wrong, remove it — do not soften it into something defensible.

### 4. Re-render

Run from the project root, via foreground Bash:

```
python <ORCH> --rerender
```

It rewrites `Findings-review[-<scope>].{json,md,-supplementary.md}` and
`Findings-intent[-<scope>].md` from the stage files, and appends a `rewrite`
row to the run report so the findings file records that it was edited by hand.
No agents, seconds not minutes.

A schema error naming `title` means one is still over 120 characters — the
renderer rejects it rather than clipping at this stage. Shorten it and re-run;
nothing was written.

A JSON parse error names the stage file you broke. Every field of every
finding is also in the rendered `Findings-review*.json` from before this run,
which is untouched until the render succeeds — rebuild the file from there.

### 5. Relay Results

Report, from the CLI's output: the finding count, the files written, and the
run-report table. Then list what you changed, one line per finding: id, old
title, new title, or `removed` plus the reason recorded.

If any id moved, say so. Ids are reassigned on every render from (path, line,
title), so retitling can renumber a bucket when two of its findings cite the
same file and line — an id the user already quoted in a PR thread may now
belong to a different finding.

## Critical Rules

- Never edit `Findings-*` files at the project root — the renderer owns them.
  Edit `.tmp-review/20-findings/` and re-render.
- Never re-run pipeline stage scripts by hand, and never `--resume-validation`
  after a rewrite: it rebuilds `20-findings/` and discards the edits.
- Never add a finding here. This skill reframes what a review found; a finding
  nothing reviewed has no evidence behind it.
- Never invent a justification for a re-rating. Cite what the conversation
  established.
