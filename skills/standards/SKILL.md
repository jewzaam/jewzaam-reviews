---
name: standards
description: Audit a repository for conformance with the user's personal coding standards at ~/source/standards/. Spawns one agent per standards subdomain, reports applicability and gaps as a Review-<project>-standards.md file compatible with /apply-review. Use when the user asks to check, audit, or validate a codebase against their standards library.
disable-model-invocation: true
allowed-tools: Bash(git remote -v),Bash(bash ~/.claude/skills/standards/scripts/applicability.sh)
---

# Standards Skill

## Purpose

Audit a repository against the user's personal standards library at `~/source/standards/`. For each standards subdomain (derived deterministically from the `## ` section headers of `~/source/standards/CLAUDE.md`) spawn a parallel agent that reads every standards file in its subdomain, decides whether each standard applies to this project, and — for applicable standards — reports gaps. Consolidate into a single review document, then validate with independent subagents. Output is consumable by `/apply-review`.

## Constraints

- **Read-only analysis.** Never modify source code, tests, or config.
- **No program execution.** Never run the target project, install dependencies, or invoke language runtimes (`python`, `node`, `go run`, etc.).
- **No package management.** Never run `pip`, `npm`, `cargo`, etc.
- **User-owned repos only.** If the pre-fetch emits `NOT_APPLICABLE`, print the reason and stop — do not write any review files.
- **Output is two files** at the project root, always with the `-standards` slug:
  - `Review-<project-name>-standards.md` — actionable findings (Critical, Important, Suggestions all in this file)
  - `Review-<project-name>-standards-supplementary.md` — per-subdomain detail, strengths, full list of non-applicable standards with reasoning
- **If review files already exist, overwrite them.**

## Pre-Fetch

### Remotes (auto-executed)

!`git remote -v || true`

### Applicability & Subdomain List (auto-executed)

Runs `scripts/applicability.sh`. Validates origin owner (`jewzaam` / `nmalik`) and `~/source/standards/CLAUDE.md` presence. On success emits one `SUBDOMAIN: <name>` line followed by `FILE: <absolute path>` lines for each standards file. On failure emits `NOT_APPLICABLE: <reason>`.

!`bash ~/.claude/skills/standards/scripts/applicability.sh`

## Process

### 1. Handle Applicability

If the pre-fetch output begins with `NOT_APPLICABLE:`, print the full reason to the user and stop. Do not write any review files. Do not proceed to the agent dispatch.

Otherwise parse the subdomain blocks. Each `SUBDOMAIN:` line starts a new group; subsequent `FILE:` lines belong to it until the next `SUBDOMAIN:` line.

### 2. Determine Project Context

- Use Glob and Read to understand the project structure.
- Identify the language, framework, build system, and test framework from top-level files (`pyproject.toml`, `package.json`, `go.mod`, `Makefile`, etc.).
- Call `mcp__allowlist__get_allowed_permissions` once to discover pre-approved commands. Pass the list to every agent so they know what can run without prompting.

### 3. Launch Subdomain Agents in Parallel

Launch one `Agent` call per subdomain from step 1, all in a single message using the Agent tool. Each agent:

- `model: "sonnet"`
- `subagent_type: "feature-dev:code-reviewer"` — structurally removes Bash/Write/Edit, enforcing read-only analysis
- Prompt built from the template below, parameterized with the subdomain name and its file list

Each agent produces, for every standards file in its subdomain, one of:

- `NOT_APPLICABLE` — with a one-line reason (e.g., "project is Go, not Python")
- `APPLICABLE` — with a structured list of gaps, each tagged with severity, confidence, `file:line`, description, why it matters, suggested fix

### 4. Consolidate Review

After all subdomain agents complete, synthesize findings into two documents at the project root.

**Deduplication rules:**
- When two agents flag the same `file:line + standard`, keep the finding from the subdomain whose standard is the better fit. Preserve the most specific reference and the most actionable fix.
- When agents disagree on severity, take the higher severity.

**Finding numbering:** Critical → `C0, C1, …`; Important → `I0, I1, …`; Suggestions → `S0, S1, …`. The prefixes must be unique across the document so `/apply-review` can target each finding.

#### Main document: `Review-<project-name>-standards.md`

```markdown
# Standards Review: <project-name>

## TL;DR
<3-5 sentence executive summary: number of subdomains audited, applicability breakdown, top gaps>

## Applicability Matrix

| Subdomain | Standard | Applies | Gap Count |
|-----------|----------|---------|-----------|
| Common | naming.md | ✅ | 2 |
| Common | versioning.md | ❌ | — |
| ... | ... | ... | ... |

## Findings

### Critical
<Issues that must be fixed — bugs, security issues, data loss risks. Number C0, C1, ...
 If none: "No critical issues identified.">

### Important
<Issues that should be fixed — error handling gaps, design problems, missing tests. Number I0, I1, ...
 If none: "No important issues identified.">

### Suggestions
<Standards-style gaps: naming, formatting, minor structure. Number S0, S1, ...
 If none: "No suggestions.">

## Recommendations
<Prioritized list of actionable next steps. End with: "Run `/apply-review Review-<project-name>-standards.md` to iteratively fix findings.">
```

#### Supplementary document: `Review-<project-name>-standards-supplementary.md`

```markdown
# Standards Review (Supplementary): <project-name>

## Strengths
<Standards the project follows well — cite the standard and where the project demonstrates it>

## Per-Subdomain Notes

### Common
<Consolidated notes from the Common agent>

### Python
<Consolidated notes from the Python agent>

<... one section per subdomain that ran ...>

## Non-Applicable Standards

| Standard | Reason |
|----------|--------|
| python/tkinter/windows.md | Project has no GUI |
| ... | ... |
```

### 5. Validate Review

For each severity tier (`Critical`, `Important`, `Suggestions`) that has **at least one finding**, spawn one validator (`model: "sonnet"`, `subagent_type: "feature-dev:code-reviewer"`) in parallel. **Skip validation entirely for any tier with zero findings** and state so in the validation summary.

Each validator:
- Reads the main review document and extracts every finding in its assigned tier
- For every finding, reads the referenced source file at the referenced line
- Challenges the finding: is the issue real, is the severity justified, is the `file:line` reference accurate, is the cited standard actually violated
- Returns a list of findings that survived, plus any that should be removed or downgraded with reasoning

After validators complete, update the main review document:
- Remove failed findings (renumber remaining to stay contiguous)
- Adjust severity for downgraded findings (re-prefix and renumber)
- Append:

```markdown
## Review Validation
<For each tier: findings validated, removed, and downgraded with brief reasoning. For skipped tiers: "Suggestions tier skipped — no findings to validate.">
```

### 6. Present Summary

Print the TL;DR, the applicability matrix row counts (`N/M standards applicable`), and the count of Critical + Important findings. Tell the user: "Run `/apply-review Review-<project-name>-standards.md` to fix findings iteratively."

## Agent Prompt Template

Each subdomain agent receives a prompt structured as:

```
Audit the project at <project-root> for conformance with the "<subdomain>" standards.

Standards files to evaluate (read ALL of them using these absolute paths):
- <absolute path 1>
- <absolute path 2>
- ...

Project context:
- Language: <detected>
- Build system: <detected>
- Test framework: <detected>
- Allowed commands: <allowlist from mcp__allowlist__get_allowed_permissions>

METHODOLOGY — work in two phases:

Phase 1 — Per-standard applicability:
For EACH standards file above, read the file and decide whether the standard applies to
this project. A standard applies if the project uses the relevant language/tool/framework
OR if the standard is language-agnostic. Record the applicability decision with a one-line
reason. Treat files in `templates/` as reference material — check whether the project's
equivalent file resembles the template, not whether it matches line-for-line.

Phase 2 — Per-standard gap assessment:
For every standard you marked APPLICABLE in Phase 1, identify specific gaps between the
standard and the project. Cite file:line. Do not flag gaps for NOT_APPLICABLE standards.

Maximize parallel tool calls — issue all independent Read/Glob/Grep calls in the same message.
Do NOT run any commands. Do NOT modify any files. Read-only analysis only.

CONFIDENCE SCORING — self-score every gap:
- High (>80%): Clear violation with concrete evidence. Report it.
- Medium (60-80%): Plausible violation but requires assumptions. Report only if critical/important.
- Low (<60%): Speculative. Drop it entirely.

SEVERITY CLASSIFICATION:
- Critical: security, data loss, breaks runtime behavior, or standard explicitly marked mandatory
- Important: affects maintainability or correctness, toolchain-enforceable, or has runtime impact
- Suggestion: metadata/style gaps with no runtime impact and not enforced by the project's toolchain

HARD EXCLUSIONS — never report these:
- Style issues already enforced by the project's own linters/formatters
- Missing tests for trivial code (getters, setters, constants)
- Generic best-practice advice not grounded in a specific file:line
- Gaps that duplicate what a project make target already checks

PROHIBITED ACTIONS:
- Do NOT write or execute ad hoc tests
- Do NOT pipe code to a runtime
- Do NOT attempt to verify findings by executing code — static analysis only

Output format — one block per standards file:

STANDARD: <filename>
APPLICABILITY: APPLICABLE | NOT_APPLICABLE
REASON: <one line>
<if APPLICABLE, followed by zero or more gaps:>
GAP:
  severity: critical|important|suggestion
  confidence: high|medium
  location: <file:line>
  description: <what is wrong>
  why: <why it matters, grounded in the standard>
  fix: <suggested change>
```

## Critical Rules

- **NEVER modify source code, tests, or config** — this is an audit, not a fix
- **NEVER install dependencies or run the program** — static analysis only
- **NEVER run package managers** — no pip, npm, cargo, etc.
- **NEVER write or execute ad hoc tests** — if a test is missing, report it as a finding
- **NEVER pipe code to a runtime** — no `echo "..." | python`, `python -c`, etc.
- **Subdomain agents and validators use `subagent_type: "feature-dev:code-reviewer"`** — Write, Edit, and Bash are structurally unavailable, not just prompted against
- **All gaps need file:line references** — no vague complaints
- **Severity must be justified** — explain why something is critical vs. suggestion
- **Acknowledge strengths** — a good audit recognizes what the project already does right
- **Only write `Review-<project-name>-standards.md` and its supplementary file** — never create or modify any other file
- **Skip empty validation tiers** — do not spawn a validator for a severity with zero findings
- **Audit is observation, not action** — `/apply-review` is the follow-up that applies fixes
