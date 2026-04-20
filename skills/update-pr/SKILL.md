---
name: update-pr
description: Incorporate feedback into a pull request. Fetches PR review comments from GitHub, accepts additional feedback from any text source (review transcripts, emails, Slack threads), generates a traceability document mapping comments to findings for upfront confirmation, walks through each comment one at a time with before/after context, and updates the document with resolutions and draft replies. This skill is invoked explicitly by the user via /update-pr -- do not trigger it automatically.
---

# Update PR with Review Feedback

This skill performs NO write operations on GitHub. No comments, no pushes, no PR updates, no review submissions, no thread resolution. All GitHub interactions are read-only fetches. The user posts replies and pushes commits themselves.

## Pre-Fetch

### Workspace Bootstrap (auto-executed)

Wipes and recreates `.tmp-update-pr/` at the project root with a `.gitignore` of `*`. Holds the pre-render JSON and any meta-issues collected during the run.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh .tmp-update-pr`

### Shared Handoff Contract (auto-injected)

!`cat ${CLAUDE_PLUGIN_ROOT}/resources/handoff-contract.md`

## Overview

The workflow has three phases:

1. **Fetch & Map** — collect all PR comments and supplementary feedback, generate a traceability document mapping comments to findings for user confirmation
2. **Review** — walk through each unresolved comment one at a time with the user, showing before/after context
3. **Apply & Update** — handle GitHub suggestions, update the traceability document with resolutions and draft replies, hand off accepted local edits to apply-review

## Before You Start

The user must provide the PR number — either as an argument (e.g., `/update-pr 1234`) or in the conversation. If they didn't provide one, ask before doing anything else.

Once you have the PR number, derive the repo owner/name from the git remote (do not run `gh repo view` — it's unnecessary). Then confirm scope with the user before fetching comments:

1. **Scope** — check which files the PR touches (`gh pr diff <PR> --name-only`) to suggest a default scope.
2. **Supplementary feedback** — note whether the user mentioned any non-GitHub feedback sources (transcripts, pasted text, files).

Present this for confirmation:
- "PR #X in owner/repo, targeting these files: [list]. Any files out of scope for changes? Any supplementary feedback to incorporate?"

Proceed only after the user confirms or adjusts. Do not report comment counts here — that information isn't available until after the Phase 1 fetch. The resolution filtering report comes at the end of Phase 1, after all comments are fetched, grouped, and filtered.

## Phase 1: Fetch Feedback

### GitHub PR Comments

Three API calls are needed. They are independent — run all three in parallel to minimize latency.

**Top-level reviews** (approve/request-changes/comment left via GitHub's Review button):

```bash
gh pr view <PR> --json comments,reviews,title,body
```

Returns:
- `reviews[]` — `.author.login`, `.body`, `.state`, `.submittedAt`
- `comments[]` — general PR conversation comments (not inline)

**Inline code review comments** (attached to specific lines in the diff):

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments
```

Each comment includes:
- `.user.login`, `.path`, `.original_line`, `.body`, `.created_at`
- `.in_reply_to_id` — parent comment ID if this is a reply in a thread

This endpoint can return large payloads (64KB+ for active PRs). If the tool harness persists the output to a file, read that file.

**Review thread resolution status** (which threads are resolved on GitHub):

```bash
gh api graphql -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          pageInfo { hasNextPage endCursor }
          nodes {
            isResolved
            comments(first: 1) {
              nodes { id databaseId }
            }
          }
        }
      }
    }
  }
' -f owner='<owner>' -f repo='<repo>' -F pr=<PR>
```

Each thread's `isResolved` flag maps to its first comment's `databaseId`, which corresponds to the `id` field from the REST inline comments endpoint. Build a set of resolved comment IDs from this data.

The `first: 100` limit covers most PRs. If `pageInfo.hasNextPage` is `true`, paginate by passing `after: <endCursor>` on subsequent requests — missing a resolved thread means its comments will incorrectly appear as unresolved.

**Data integrity:** Comment bodies — especially suggestion blocks — must never be truncated. Read every comment body in full. Suggestion blocks contain the exact proposed replacement text and must be compared character-by-character against the current file to determine if they've already been applied.

### Supplementary Feedback

If the user indicated supplementary feedback sources:
- **Review transcripts** — files containing notes from verbal reviews or recorded walkthroughs
- **Pasted text** — feedback from email, Slack, or other channels
- **Referenced files** — files in the repo containing feedback

Read and extract feedback items from these sources.

### Group Reply Chains

Before reviewing, group threaded comments using `in_reply_to_id`. PR comments often have reply chains where feedback evolves — a reviewer may clarify, soften, or retract their original point in a follow-up. When a thread exists:

- Read the full thread to understand the final position
- If a later reply retracts or supersedes the original feedback, treat the thread as a single unit reflecting the final state
- Attribute the thread to the original commenter unless a different reviewer's reply changes the nature of the feedback

### Cross-Check Comment Count

After grouping, verify that every fetched comment appears in exactly one group (standalone or threaded). The total number of individual comments across all groups must equal the total number of fetched comments. Flag any discrepancy before proceeding — a missing comment means a reviewer's feedback could be silently ignored. This check is about grouping completeness, not review count — the number of groups to review will be smaller after resolved threads are filtered in the next step.

If the PR has no GitHub comments and no supplementary feedback was provided, report this to the user and stop — there is nothing to review.

### Filter Out Resolved Comments

Using the resolution status from the GraphQL query, remove all comments belonging to resolved threads. Resolved threads are always skipped — this is not optional and should never be presented as a choice to the user. Only unresolved threads and supplementary feedback items proceed to Phase 2.

Report the filtering result before starting Phase 2: "N comments fetched, M already resolved on GitHub, K unresolved comments to review." If all comments are resolved and there's no supplementary feedback, report this and stop — there is nothing to review.

### Generate Review Traceability Document

After filtering, build a pre-render JSON at `.tmp-update-pr/pre-render.json`. The workspace bootstrap pre-fetch already created the dir with its `.gitignore`. This is the structured input that `render-update-pr.py` turns into the authoritative JSON + rendered markdown.

**Constraint: no new findings.** Findings consolidate what reviewers raised — nothing more. If a comment doesn't map to a broader finding, it stands alone. The skill's role is to organize and present reviewer feedback, not to perform independent code review.

**Pre-render JSON shape (Phase 1 state — no resolutions yet):**

```json
{
  "project": {"name": "<repo-or-project-name>"},
  "findings": [
    {
      "id": "I0",
      "title": "<short title>",
      "severity": "important|suggestion",
      "locations": [{"path": "<file>", "line": "<N>", "role": "primary"}],
      "issue": "<what reviewers flagged>",
      "why_it_matters": "<why it matters, paraphrased from reviewer comments>",
      "suggested_fix": "<from reviewer comments, not independent analysis>",
      "pr_comment": {"author": "<reviewer>", "id": <comment_id>}
    }
  ],
  "supplementary": {
    "pr_title": "<PR title>",
    "counts": {"total": <N>, "resolved": <M>, "unresolved": <K>},
    "traceability": {
      "<reviewer_handle>": [
        {
          "summary": "<condensed feedback>",
          "location": "<file:line>",
          "finding": "<finding-id or —>"
        }
      ]
    }
  }
}
```

Then invoke:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/update-pr/scripts/render-update-pr.py \
  --input .tmp-update-pr/pre-render.json \
  --out-dir <repo root> \
  --pr-number <number>
```

Skill-specific renderer behavior (on top of the shared handoff contract):
- Emits `source: "review"` (PR review is a review with `pr_comment` extensions on findings).
- Writes `Findings-update-pr-<number>.json` (authoritative) and `Findings-update-pr-<number>.md` (rendered traceability).

Format rules (enforced by schema and/or script):
- **Finding IDs** use standard review prefixes — `I0`, `I1` for important issues, `S0`, `S1` for suggestions, `C0`, `C1` for clarifications — sequential within each category. Severity assessment is out of scope; the prefix indicates the type of reviewer feedback (proposed fix vs. suggestion vs. question), not a priority ranking.
- **Every finding must trace to at least one PR comment.** If a finding has no `pr_comment` link in the pre-render JSON, it was invented — remove it. This is the hard constraint.
- **Every unresolved comment must appear in exactly one reviewer's traceability list.** Cross-check the total against the filtered count before invoking the renderer.
- **Comment numbering is local** — the rendered table's `#` column starts at 1 per reviewer and is only meaningful within this document.
- **Standalone comments** (finding field "—") are valid — not every comment needs to be part of a broader finding. These proceed to Phase 2 as individual items.
- **Resolved comments are excluded** from the traceability — they appear only in the `counts` summary.

Use `AskUserQuestion` to present the document and wait for confirmation before proceeding to Phase 2:

```
Review traceability document generated: Findings-update-pr-<number>.json (+ .md view)

<K> unresolved comments mapped to <F> findings, <S> standalone.
<M> resolved comments excluded.

Please review the document. You can:
- Adjust finding groupings (split or merge)
- Remove findings you consider invalid
- Flag comments that were miscategorized

Confirm to proceed, or describe adjustments.
```

Incorporate any adjustments by editing the pre-render JSON and re-running the render script, then proceed to the interactive walkthrough.

## Phase 2: Review Each Comment

Walk through each **unresolved** comment one at a time. This is a single pass — categorization and the user's decision happen together. Never batch multiple items into one question. Never present resolved comments — they were filtered out in Phase 1.

Even when multiple comments map to the same finding, present each comment individually — the user needs to provide a reply to each one. For example, if comments #3, #7, and #12 all map to finding I0, present three separate questions. Reference the finding ID in each question so the user sees the connection, but each comment gets its own decision.

### Before/After Context Is Mandatory

For every comment that references a code or text change, read the actual file content at the referenced location. The user cannot evaluate a change without seeing the concrete diff. Do not describe changes in prose when you can show the text.

**Line mapping caveat:** After force-pushes, the `original_line` from the API refers to a line in the original diff, not the current file. Use the comment body and surrounding context (quoted code, suggestion blocks) to locate the correct position in the current file rather than trusting the line number blindly. Search for the quoted text in the file to find the actual location.

### Determine Comment Type

Each comment falls into one of two types, which determines the decision flow:

**Change comments** — the reviewer proposes a specific modification (suggestion block, requested edit, or rewrite). These need a code decision:

- **Accept** — apply the change as proposed
- **Reject** — don't apply; user provides reasoning for their reply
- **Already applied** — the change was already made in a prior commit

**Discussion comments** — questions, observations, or feedback that don't propose a specific change. These need a reply decision:

- **Answer** — user provides the answer to include in their draft reply
- **Acknowledge** — user agrees or notes the feedback
- **Defer** — valid but out of scope; user provides reasoning
- **No action needed** — approval, praise, or already-answered questions

### Mandatory Question Format

Use `AskUserQuestion` for each item. The question text must follow this structure — do not deviate:

For **change comments**, include before/after context:

```
**[reviewer_handle] on [file]:[line]:** [condensed feedback]

> [reviewer's quoted comment, or suggestion block content]

- Before: [exact current text from the file, quoted]
- After: [exact proposed replacement text, quoted]

What would you like to do?
```

Options: Accept | Reject | Already applied

For **discussion comments**:

```
**[reviewer_handle] on [file]:[line] (or "top-level review"):** [condensed feedback]

> [reviewer's quoted comment]

How would you like to handle this?
```

Options: Answer | Acknowledge | Defer | No action needed

The user can always select "Other" to provide free-form text. Whatever the user says — option, notes, or free-form — becomes the basis for the draft reply in the summary document. Capture their words faithfully; this is what they'll adapt when posting on the PR.

### Reviewer References

When referring to reviewers in questions or the output document, use their handle directly (e.g., "jane requested..." not "she requested...") or use "they/them" as default neutral pronouns. Never infer gender from names.

### Already-Applied Verification

Before categorizing any comment as "already applied," diff the suggestion or proposed change against the current file content. If they don't match exactly, it's a change comment that needs a decision. Partial matches (e.g., the suggestion includes additional text beyond what was applied) are not "already applied."

## Phase 3: Apply Changes & Generate Summary

### Step 1: Separate GitHub Suggestions from Local Edits

After the review pass, separate accepted changes into two groups:

**GitHub-mergeable suggestions** — accepted items that have a GitHub `suggestion` block. Applying these through the GitHub UI creates a commit credited to the reviewer, which is valuable for team dynamics and PR history. If the user accepted a suggestion but added modifications via free-form text, apply the suggestion on GitHub first, then apply the user's revision locally after pulling — this preserves reviewer attribution for the base change while layering the user's modifications.

**Local edits** — everything else (items without suggestion blocks, alternatives, revisions on top of merged suggestions, and cleanup work).

### Step 2: GitHub Suggestions First

Present the GitHub-mergeable suggestions to the user via `AskUserQuestion`. Include the count and a checklist:

```
N suggestions can be applied via GitHub's "Apply suggestion" button for reviewer attribution.
Which would you like to handle on GitHub?
```

For each suggestion, show the reviewer, file, and the change. Options for each:
- **I'll apply on GitHub** — user will apply it in the PR UI
- **Apply locally instead** — skip GitHub attribution, apply as a local edit
- **Already applied** — user already merged it

After the user indicates which ones they'll apply on GitHub, instruct them:

1. Apply the suggestions on the GitHub PR page
2. Stash any uncommitted local changes (`git stash`)
3. Pull the new commits (`git pull`)
4. Restore local state (`git stash pop`)

Wait for the user to confirm they've completed this. Then verify each suggestion landed by reading the file and confirming the expected text is present. Report any that didn't land before proceeding.

### Step 3: Cross-Check — Every Comment Needs a Resolution Path

Before generating the summary, verify every fetched comment has a clear resolution:

| Resolution type | What happened | Reply needed? |
|---|---|---|
| Applied via GitHub suggestion | Reviewer gets commit attribution | No (GitHub auto-marks) |
| Accepted for local edit | Handed off to apply-review | Yes — draft a reply noting the planned change |
| Rejected | No code change | Yes — draft a reply with user's reasoning |
| Discussion answered | No code change | Yes — draft the answer |
| Deferred | Out of scope | Yes — draft a reply with reasoning |
| Already applied | Changed in a prior commit | Yes — brief reply noting which commit |
| Resolved on GitHub | Thread already resolved before this run | No — already handled |
| No action needed | Approval, praise | No |

Flag any comment that lacks a resolution path. Every reviewer comment (except pure approvals) should map to either "resolved by code change" or "needs reply to draft."

### Step 4: Update Traceability and Generate Summary

Extend the `.tmp-update-pr/pre-render.json` from Phase 1 by adding `supplementary.resolutions` and resolution columns in the traceability rows. Then re-run the render script (same invocation as Phase 1) to regenerate `Findings-update-pr-<number>.json` and `.md` with resolutions included.

**Resolutions shape in `supplementary.resolutions`:**

```json
{
  "resolutions": {
    "draft_replies": [
      {
        "reviewer": "<handle>",
        "location": "<file:line>",
        "decision": "Accepted | Rejected | Deferred | Already applied | Discussion answered",
        "summary": "<condensed feedback>",
        "reply": "<reply text in user's voice>"
      }
    ],
    "re_request": [
      {"reviewer": "<handle>", "note": "<brief note on what was addressed>"}
    ],
    "applied_via_github_suggestions": [
      {"reviewer": "<handle>", "location": "<file:line>", "summary": "<short>"}
    ],
    "pending_local_edits": [
      {"reviewer": "<handle>", "location": "<file:line>", "finding": "<ID>", "summary": "<short>"}
    ],
    "no_action": [
      {"reviewer": "<handle>", "summary": "<short>"}
    ]
  }
}
```

Also add a `resolution` field to each row in `supplementary.traceability[<reviewer>]` (e.g., `"Pending — apply-review"`, `"Applied via suggestion"`, `"Rejected"`). The render script detects the field's presence and renders an extra column in the traceability table.

Format rules:
- **Draft replies should use the user's voice** — they reflect the user's own words from the interactive review. This is the text they'll adapt when posting on the PR, so preserve their intent and tone.
- **Single source of truth** — `pre-render.json` is hand-edited; the script renders both `Findings-update-pr-<number>.json` and `Findings-update-pr-<number>.md` from it. Do not hand-edit either output file.
- **Checkbox semantics** — the script emits `- [ ]` for draft replies and re-request items (actions the user performs) and plain bullets for informational sections. This is driven by the script, not by your JSON shape.

### Step 5: Hand Off Local Edits to apply-review

Do not apply local code changes directly. Delegate to the `apply-review` skill, which has the per-finding discipline (implement, validate, handoff, stage, commit).

Collect the finding IDs for all accepted local edits. Then use `AskUserQuestion` to hand off:

```
Local edits are ready to apply. When you're ready, run:

/apply-review Findings-update-pr-<number>.json I0 I2 S0

This will apply each finding as an isolated, tested, committed change.
```

Note the `.json` extension — `/apply-review` consumes the authoritative JSON directly. The `.md` file is human-readable but not parsed.

The finding IDs listed must be exactly the accepted local edits — exclude GitHub suggestions (already applied), rejected items, deferred items, and discussion-only comments.

This is a gate — the user must acknowledge it. Do not apply code changes in this skill. The skill's job ends with the traceability document and draft replies.

If there are no accepted local edits (all items were GitHub suggestions, rejections, deferrals, or discussion), skip this step — there is nothing to hand off.

### After Generating the Summary

Report to the user:
- Total comments fetched
- Breakdown: already resolved on GitHub, applied via GitHub suggestion, accepted for local edit (pending apply-review), rejected, deferred, no action needed
- Count of draft replies to post
- Count of reviewers to re-request
