---
name: review
description: Perform a multi-agent codebase review by spinning up parallel review agents across multiple dimensions (1 + 7×N agents per run). Use when the user asks to review, assess, audit, or evaluate a codebase or project. Accepts an optional PR number and/or free-form guidance text to focus the review.
disable-model-invocation: true
argument-hint: "[PR-number] [guidance text...]"
allowed-tools:
  - Bash(git remote -v)
  - Bash(make -n *)
  - Bash(make format)
  - Bash(make format-check)
  - Bash(make lint)
  - Bash(make typecheck)
  - Bash(make test)
  - Bash(make test-unit)
  - Bash(make coverage)
  - Bash(make complexity)
  - Bash(ls *)
  - Bash(test -f *)
  - Bash(test -d *)
  - Read(${CLAUDE_SKILL_DIR}/**)
  - Glob(${CLAUDE_SKILL_DIR}/**)
  - Grep(${CLAUDE_SKILL_DIR}/**)
  - Read(${CLAUDE_SKILL_DIR}/*:*)
  - Glob(${CLAUDE_SKILL_DIR}/*:*)
  - Grep(${CLAUDE_SKILL_DIR}/*:*)
  - Read(${CLAUDE_SKILL_DIR}/*)
  - Glob(${CLAUDE_SKILL_DIR}/*)
  - Grep(${CLAUDE_SKILL_DIR}/*)
  - Write(./.tmp-review/raw/**)
  - Write(**/.tmp-review/raw/**)
  - Bash(${CLAUDE_SKILL_DIR}/scripts/:*)
  - Bash(python ${CLAUDE_SKILL_DIR}/scripts/:*)
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/:*)
  - Bash(bash ${CLAUDE_SKILL_DIR}/**)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh:*)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-handoff-contract.sh:*)
---

# Review Skill

## Purpose

Perform a multi-agent review of a codebase by spinning up parallel review agents across multiple dimensions. Produce a single consolidated review document, then validate it with an independent agent.

## Constraints

- **Script paths use `~`:** Use the **Plugin Home** path from the Pre-Fetch section (starts with `~`) when constructing Bash commands for plugin scripts. Do not use absolute `/home/...` paths. Do not use `&&` or `||` chaining — each script call must be a standalone Bash invocation.
- **Read-only analysis of source code.** Never modify the user's source code or tests.
- **No program execution.** Never install dependencies, run the program, or execute language runtimes directly (no `python -c`, `node`, `go run`, etc.) against the user's code.
- **No package management.** Never run `pip`, `npm`, `cargo`, etc.
- **Output is two markdown files plus one JSON file** at the project root: `Findings-review.md` (actionable findings), `Findings-review-supplementary.md` (detailed analysis, strengths, decomposition), and `Findings-review.json` (structured findings for downstream skills). Filenames follow the plugin-wide pattern `Findings-<skill-name>[-<scope-slug>].{json,md}` for producer skills (apply-review is a consumer and emits `Report-apply-review.json`) — the skill name identifies the producer; project identity lives in the JSON envelope's `project.name`. If the user provides constrained context (a PR number, specific area, topic), append a scope slug (max 12 chars, lowercase, hyphens): `Findings-review-<slug>.{json,md,-supplementary.md}`.
- **Intermediate workspace is `./.tmp-review/` at the project root** — created by the bootstrap pre-fetch, contains a `.gitignore` of `*` so it is never committed. Holds raw per-agent JSON, the consolidated set, and validation batches.
- **If a check requires a tool not present**, note it in the review as a recommendation — do not attempt to install or build it.

## Pre-Fetch

### Plugin Home (auto-detected)

Plugin root with `~` prefix. Use this path in all Bash commands that invoke plugin scripts.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-plugin-home.sh ${CLAUDE_PLUGIN_ROOT}`

### Project Root (auto-detected)

Absolute path of the project root. The main agent MUST substitute this value for any `./.tmp-review/...` path it passes to a dispatched sub-agent, so the sub-agent has an unambiguous absolute Write target and cannot drift to `/tmp/` or any other directory.

!`pwd`

### Remotes (auto-executed)

!`git remote -v || true`

### Standards Applicability (auto-executed)

Runs `scripts/standards-check.sh`. For user-owned repos (origin owner matches `gh` login and `~/source/standards/` exists), injects the external standards CLAUDE.md with all relative links rewritten to absolute paths (e.g., `common/naming.md` becomes `~/source/standards/common/naming.md`). For non-owned repos, outputs nothing — project standards are already in context via Claude Code.

!`bash ${CLAUDE_SKILL_DIR}/scripts/standards-check.sh`

### Findings Workspace Bootstrap (auto-executed)

Wipes and recreates `./.tmp-review/` at the project root with `raw/`, `validation/`, and a `.gitignore` of `*`. Each `/review` invocation starts from a clean slate so stale findings from a prior run cannot leak into consolidation. Sub-agents and the main agent both write JSON into this tree.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh .tmp-review raw validation`

### Shared Handoff Contract (auto-injected)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-handoff-contract.sh`

### PR Scope (auto-executed)

If the first argument is numeric, computes the changed files against the default branch merge base. Output is injected as PR scope context for diff-scoped reviews. Any non-numeric trailing arguments are handled by the User Guidance step below. Outputs nothing if no numeric leading argument is given.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/pr-scope.sh "$ARGUMENTS"`

### User Guidance (auto-executed)

Extracts free-form guidance text from the arguments (everything after a leading PR number, or all arguments if none is numeric) and emits it as a "User Guidance" section. The main agent interprets the guidance and decides how it affects the review. Outputs nothing if no guidance is supplied.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/guidance.sh "$ARGUMENTS"`

## Process

### 1. Determine Scope & Context

- If the pre-fetch injected a "PR Scope" section, include it verbatim in each agent's prompt.
- If the pre-fetch injected a "User Guidance" section, include it verbatim in each agent's prompt. Interpret the guidance yourself — it may be a focus hint, a narrowing filter, a specific question, or arbitrary context. Apply it as the user would reasonably expect.
- Use Glob and Read to understand the project structure.
- Identify the language, framework, build system, and test framework.

**Standards detection:** Discover local project standards by reading `CLAUDE.md` and `AGENTS.md` at the project root, if they exist. These files define project conventions, coding rules, and behavioral instructions that the review should check against.

Follow explicit file path references found in rules or instructions sections (e.g., "see `docs/contributing.md`", "follow the style guide at `STYLE_GUIDE.md`"). Only follow paths that are clearly pointed to as standards, conventions, or guidelines — ignore casual mentions of source files, config paths, or directories referenced as examples. Follow references up to 2 levels deep (a standards file may reference another, but stop there). Collect all discovered standards into a local standards context and pass relevant portions to each agent — summarize or select sections pertinent to each agent's review area rather than dumping everything.

**External standards:** For user-owned repos, the pre-fetch injects the external standards index with absolute paths directly into context. Pass this content to each agent as part of their prompt — agents can Read any referenced file directly using the absolute paths. For non-owned repos, the pre-fetch outputs nothing and agents rely solely on the project's own CLAUDE.md (already loaded by Claude Code).

**Allowlist discovery:** Call `mcp__allowlist__get_allowed_permissions` once to discover which commands are pre-approved. Include the allowed commands in each agent's prompt so agents know what they can run without blocking on user approval.

### 2. Decompose Scope into Dimensions

A **dimension** is a coherent slice of the review scope handed to a set of review agents. Decomposition decides how the work is sliced before any agent is dispatched.

**What can count as a dimension** (these are examples — pick whatever shape best matches the scope; do not feel obligated to use any specific one):
- A directory or sub-tree
- A package or module
- A logical theme (e.g., "auth", "data ingestion", "config layer")
- A cross-cutting concern (e.g., "security across all routes", "all CLI entry points")
- A single file *only when the entire scope is 1–2 files*; do not split a larger scope into one-dimension-per-file (that explodes agent counts without value)

**Decomposition rules:**
- **Default to decomposing.** For any meaningful scope, identify multiple dimensions. The only exception: when the scope is 1–2 files (a tiny PR or a single-file review), a single dimension covering them is acceptable — do not artificially split.
- **No cap on dimension count.** Large repos may produce 10+ dimensions and dozens of agents. Token cost is the explicit trade-off; the user has opted in.
- **Overlap is allowed.** Dimensions may overlap (e.g., a per-package dim plus a cross-cutting "security" dim). Consolidation deduplicates findings.
- **PR-scoped reviews:** derive dimensions from the changed file set. **Full-repo reviews:** derive from the project structure.
- For each dimension produce: a short human-readable name (e.g., `"auth subsystem"`), a filesystem-safe slug (lowercase, hyphens, ≤30 chars), and a `dimension_scope` object describing what the agent will review (e.g., `{"paths": ["src/auth/"]}` or `{"theme": "all CLI entry points", "paths": ["src/cli/"]}`).
- Record the full dimension list — you will write it into the supplementary review file at the render step.

### 3. Dispatch the Review Agent Matrix

After decomposition produces N dimensions, launch **all `1 + 7×N` agents in a single parallel message** using the Agent tool.

- **1 × Build & Checks agent** (global, runs once)
- **For each dimension:** 7 concern agents — one per concern axis below

#### Build & Checks Agent

- `model: "haiku"`, default subagent_type
- Runs available `make` check targets sequentially via Bash and reports pass/fail. Prefer commands from the provided allowlist.
- Safe targets to attempt (skip if missing): `make format-check` (or `make format` in check mode), `make lint`, `make typecheck`, `make test` or `make test-unit`, `make coverage`, `make complexity`.
- **The Build & Checks agent is the only agent that runs anything against the user's project.** Concern agents must not invoke complexity tools (radon, xenon), test runners, or any other analysis tools directly — if a check is worth running, it belongs in a `make` target the Build & Checks agent invokes.
- Do **not** run `install`, `build`, `run`, `deploy`, or any target that installs or executes the program.
- **Output guidelines:** summarize failures concisely — error type and affected files, not full stack traces. For missing-dependency failures, state which dependency is missing and move on.

#### Concern Axes (per dimension)

| # | Concern (`concern`) | `concern_slug` | Model | Scope |
|---|---|---|---|---|
| 1 | Architecture & Design | `architecture` | sonnet | Project structure, module boundaries, coupling, data model, configuration management, design pattern consistency. |
| 2 | Implementation Quality | `implementation` | sonnet | Logic correctness, error handling, type safety, resource management, edge cases, concurrency. **Security excluded — see dedicated axis.** |
| 3 | Test Quality & Coverage | `test` | sonnet | Test plan alignment, isolation, assertion quality, edge case coverage, mock usage, missing scenarios, fixture design. |
| 4 | Maintainability & Standards | `maintainability` | haiku | Naming, duplication, import organization, function complexity, internal consistency, build system. **Documentation excluded — see dedicated axis.** |
| 5 | Security | `security` | sonnet | Authn/authz, input validation, injection vectors, credential/secret handling, path traversal, deserialization, supply chain (deps), TLS/crypto, auth-related error leakage. |
| 6 | Documentation | `documentation` | haiku | README accuracy and completeness, docstrings, inline comments where non-obvious, examples, ADRs, changelog, public API docs, install/usage instructions. |
| 7 | Observability | `observability` | sonnet | Log quality (levels, structured fields, sensitive data), error context (do exceptions carry enough info?), metrics, traces, debug affordances, alerting hooks. |

#### Subagent Type and Tool Restrictions

All seven concern agents use `subagent_type: "general-purpose"`. They need both Write (to put their JSON output on disk) and Bash (to invoke `validate-findings.py`) to self-validate against the schema. The prompt restricts them as follows:

- **Pre-assigned output path:** each agent is told its single allowed Write target as an **absolute path**, built by prefixing the injected `pwd` value (from the Pre-Fetch "Project Root" section) to `/.tmp-review/raw/<concern_slug>-<dimension_slug>.json`. Example: if `pwd` printed `/home/user/proj`, the agent's Write target is `/home/user/proj/.tmp-review/raw/architecture-auth.json`. Never hand the agent a bare relative path — sub-agent CWD handling is unreliable and bare relative paths have led to writes drifting into `/tmp/`. Any Write to any other path is a violation.
- **Bash restricted to one command pattern:** invoking `validate-findings.py` against that exact absolute output path. No other Bash usage is permitted.
- **Edit, NotebookEdit, and any other state-modifying tool are prohibited.**
- The agent must stop and report if asked or tempted to deviate.

#### Methodology (per concern agent)

Each concern agent operates in two phases within its dimension scope:
1. **Establish baseline patterns:** read enough code in scope to understand the project's existing conventions for this concern. This grounds the review in the project's own patterns, not abstract ideals.
2. **Assess against baseline:** flag deviations and gaps. Score each finding numerically.

#### Scoring (per finding)

Each finding is scored on four integer scales (0–100). Names match the JSON schema fields exactly:

- `impact` — how bad if the issue manifests / blast radius.
- `likelihood` — probability the issue actually occurs in real use.
- `effort_to_fix` — rough cost (lower = cheaper). Helps downstream tools prioritize quick wins.
- `confidence` — the agent's certainty that this is a real issue with concrete evidence.

**Sub-agents do not drop low-confidence findings.** Every finding the agent identifies enters the pipeline. Validators may rescore later (including increasing confidence); the render step segregates low-confidence items into the `needs-review` bucket.

The `agent-output` schema does not include `severity` or `id` fields — the schema rejects either. Severity buckets and IDs are computed at the render step from the numerical scores; sub-agents do not need to think about them.

#### Hard Exclusions — Do Not Report

- Style issues already enforced by project linters or formatters (check for `.flake8`, `pyproject.toml [tool.ruff]`, `.eslintrc`, etc.)
- Missing tests for trivial code (getters, setters, simple data classes, constants)
- Architecture concerns in `scripts/`, one-off utilities, or exploratory code
- Suggestions that repeat what a make target already checks
- Missing docstrings on internal/private functions
- Generic best-practice advice not grounded in a specific code location

### 4. Re-Validate Per-Agent JSON

After every concern agent returns, re-run the validator as defense-in-depth:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py ./.tmp-review/raw/<concern_slug>-<dimension_slug>.json
```

For any file that fails this re-validation, exclude it from consolidation and log a warning in the supplementary "Decomposition" preamble (you will write that preamble at render time). Do not re-dispatch — sub-agents already had three attempts.

### 5. Consolidate

Run the consolidator script — it applies the merge rules deterministically and emits a schema-validated `consolidated.json`:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/consolidate-findings.py \
  --raw-dir ./.tmp-review/raw/ \
  --output ./.tmp-review/consolidated.json \
  --issues-out ./.tmp-review/issues.json \
  --project-name <project name> \
  --scope-slug <slug if PR-number or guidance constrained scope, else omit> \
  --cross-concern-threshold 0.4
```

`--issues-out` appends one `schema_rejected_input` issue per skipped raw file to `./.tmp-review/issues.json`, so the final envelope carries a machine-readable record of any per-agent output that was rejected by the agent-output schema. The render step later reads the same file via its own `--issues` flag.

What the script does (you do **not** re-implement this in your reasoning):

- **Pass 1: group by `(concern_slug, primary location)`.** Primary location is the first entry in `finding.locations` whose `role` is `primary` (or absent — defaulted to primary). Within each group: union `locations` (dedup by `path` + `line`), keep the longest non-trivial `suggested_fix` (tie-break by `dimension_slug`), take **max** of `impact`/`likelihood`/`confidence`, **min** of `effort_to_fix`, sorted union of `dimension_slug` → `source_dimensions`.
- **Pass 2: cross-cutting merge within concern.** Within the same `concern_slug`, group remaining findings by title similarity (Jaccard over lowercased alphanumeric tokens, default threshold `--similarity-threshold 0.7`) and merge near-duplicates using the same numerical aggregation.
- **Pass 3: cross-concern merge at same location.** Across different `concern_slug` values, findings whose primary location is identical are grouped and sub-clustered by title similarity at a (typically lower) threshold of `--cross-concern-threshold` (default 0.4). The merged finding's `concern_slug` is taken from the highest-priority contributor (`impact * likelihood / 100`, alphabetical tie-break). Same numerical aggregation rules as Pass 1.
- **Content hash.** Each merged finding gets a 16-char hex SHA-256 prefix over `(concern_slug, dimension_slug of first contributor, primary location path:line, title)`.
- **Decomposition.** Built from the per-agent `dimension_name`/`dimension_slug`/`dimension_scope`, deduplicated by `dimension_slug`.
- **No IDs. No severity buckets.** Both are assigned only at render time.
- Output is validated against `consolidated.schema.json` before writing; the script exits non-zero on any validation error.

If a `raw/*.json` file fails its agent-output schema validation, the consolidator skips it with a warning on stderr and continues. Note any skipped files in the supplementary "Decomposition" preamble at render time.

### 6. Validate Findings

Run the batcher script — it slices `consolidated.json` into validation-input batches and self-validates each against the schema:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/batch-findings.py \
  --input ./.tmp-review/consolidated.json \
  --output-dir ./.tmp-review/validation/
```

What the script does (you do **not** re-implement this in your reasoning):

- Sorts findings by `priority` (= `impact * likelihood / 100`) descending; deterministic tie-break on `content_hash`.
- Slices into batches of at most **8** findings each (the spec's hard cap; `--batch-size` overrides but cannot exceed 8).
- Writes `batch-<N>-input.json` per batch containing `{batch_number, total_batches, findings: [...]}`.
- Each batch finding's `index` field is its **original position in `consolidated.findings`** — verdict application uses `consolidated.findings[verdict.finding_ref.index]`. Sorting does NOT renumber it.
- Strips fields not in the validation-input schema (e.g. `source_dimensions`).
- Validates every batch against `validation-input.schema.json` before writing; exits non-zero on any failure.

Spawn `total_batches` validator agents in **parallel** in a single message:

- `model: "sonnet"`, `subagent_type: "feature-dev:code-reviewer"` (read-only structurally).
- Each validator opens the cited `finding.locations`, challenges accuracy and the four numerical scores, and returns a JSON object matching `validation-output.schema.json` directly in its response.
- Each verdict is one of:
  - `"action": "confirm"` — finding stands as-is.
  - `"action": "rescore"` — provide `new_scores` with any subset of the four fields. Validators may *increase* `confidence` if they find stronger evidence.
  - `"action": "remove"` — finding is wrong (e.g., cited line does not exist, issue is not real).
- Each verdict carries `finding_ref: {index, content_hash}` so the main agent can detect array drift. **Copy the `index` and `content_hash` verbatim from the input batch finding** — do NOT renumber by batch-local position (0..N within the batch), do NOT recompute the hash, and do NOT pair a `content_hash` from one finding with the `index` of another. The main agent drops any verdict whose `content_hash` doesn't match `consolidated.findings[index].content_hash` — this is the guardrail against silent mutation of the wrong finding, but it also means a drift-producing verdict is silently discarded.

After each validator returns, write its response to `./.tmp-review/validation/batch-<N>-output.json` and re-validate it against `validation-output.schema.json`.

### 7. Apply Verdicts and Render

Apply verdicts to `consolidated.json` **in your own reasoning** — do not write or execute any helper script for this step:

- **No ad-hoc helper scripts.** Do NOT create `apply_verdicts.py`, `merge.py`, `apply.py`, or any other Python/Bash file to automate verdict application. The skill ships exactly three scripts in `${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/` (`consolidate-findings.py`, `validate-findings.py`, `render-review.py`) — that set is closed. Adding another script at runtime — especially by Writing into `./.tmp-review/` and then `mv`-ing it into `${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/` to get around the Bash allowlist — is a hard violation. The plugin tree is read-only from inside a skill run.
- **No writes outside `./.tmp-review/` and the three final output files.** The only permitted Write targets for the main agent during Step 7 are `./.tmp-review/post-validation.json`, `./.tmp-review/issues.json`, `Findings-review[-<slug>].json`, `Findings-review[-<slug>].md`, and `Findings-review[-<slug>]-supplementary.md`. Any other Write — to `${CLAUDE_PLUGIN_ROOT}/...`, to `docs/`, to `scripts/`, to `/tmp/`, anywhere — is a violation.

Verdict application procedure (in memory):

- For each verdict, look up the finding by `index` and confirm `content_hash` matches. If the hash mismatches, log the discrepancy and skip the verdict (do not mutate the wrong finding).
- `"confirm"`: no change.
- `"rescore"`: shallow-merge `new_scores` into the finding's numerical fields.
- `"remove"`: drop the finding from the list.
- Findings with low `confidence` are kept; the renderer segregates them.

Write the post-validation findings to `./.tmp-review/post-validation.json` (same shape as `consolidated.json`) and any meta-issues to `./.tmp-review/issues.json` (see the injected Shared Handoff Contract for the issue shape).

Before invoking the renderer, validate `post-validation.json` against the shared consolidated schema — this catches any malformed rescore values before a partial artifact can be written:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py ./.tmp-review/post-validation.json
```

(Auto-detection recognises `./.tmp-review/post-validation.json` as the `consolidated` schema; passing `--schema consolidated` explicitly is equivalent.)

Then run the renderer:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/render-review.py \
  --input ./.tmp-review/post-validation.json \
  --config ${CLAUDE_PLUGIN_ROOT}/skills/review/schemas/render-config.default.json \
  --issues ./.tmp-review/issues.json \
  --out-dir <project root> \
  --project-name <project name> \
  --scope-slug <slug if PR-number or guidance constrained scope, else empty>
```

Skill-specific renderer behavior (on top of the shared contract):
- Maps each finding to a severity bucket (`critical | important | suggestion | needs-review`) using the threshold config.
- Assigns IDs in stable per-bucket order: `C0..`, `I0..`, `S0..`, `N0..`.
- Writes three files: `Findings-review[-<slug>].json`, `.md`, `-supplementary.md`.

The slug derivation from `/review` arguments matches today's behavior (max 12 chars, lowercase, hyphens; appended when scope is constrained by PR number or guidance text). Pre-existing PR-scope and user-guidance pre-fetch outputs supply the source material.

### 8. Present Summary

After rendering, present the TL;DR plus the Critical and Important findings inline to the user. Reference the main markdown file for full details and the supplementary file for analysis, suggestions, and needs-review items. Reference the JSON file for downstream tooling.

## Sub-Agent Prompt Template (concern agents)

Each of the seven concern agents per dimension receives a prompt structured as follows:

```
You are reviewing the project at <root-path> for the **<concern>** axis within the dimension **<dimension_name>** (slug: <dimension_slug>).

DIMENSION SCOPE (confine your review to this):
<JSON object: file list, directory paths, or theme description>

If you notice issues clearly outside this scope, list them under `cross_cutting_observations` in your output but do not investigate deeply.

OUTPUT PATH (your single allowed Write target):
./.tmp-review/raw/<concern_slug>-<dimension_slug>.json

TOOL RESTRICTIONS — strictly enforced:
- Write: only to the OUTPUT PATH above. Any Write elsewhere is a violation; stop and report.
- Bash: only to invoke `python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py <OUTPUT PATH>`. No other Bash usage is permitted.
- Edit, NotebookEdit, or any other state-modifying tool: prohibited.
- TaskCreate, TaskUpdate, TodoWrite, and other task-tracking tools: do NOT use them. Your scope is narrow (one concern × one dimension); track progress inline in your own reasoning — there is no multi-step plan worth persisting, and these tools' schemas are deferred so calls will fail on first attempt and waste context.
- For reading and searching, use Read, Glob, Grep, LS as needed. Other tools (WebFetch, WebSearch, etc.) are available but rarely useful for in-scope review work.

PROJECT CONTEXT:
- Language: <detected>
- Build system: <detected>
- Test framework: <detected>
- Allowed commands: <allowlist from mcp__allowlist__get_allowed_permissions>
- Local standards: <relevant standards from CLAUDE.md, AGENTS.md, and referenced files>
<if external standards were injected>
- External standards: <injected content with absolute paths> — read the relevant files for your axis and check compliance.
</if>
<include PR Scope output verbatim, if any>
<include User Guidance output verbatim, if any>

METHODOLOGY:
Phase 1 — Establish baseline patterns:
Read enough code in scope to understand the project's existing conventions for the <concern> axis. This grounds the review in the project's own patterns.

Phase 2 — Assess against baseline:
Evaluate whether the codebase follows its own patterns consistently. Flag deviations, gaps, and concrete issues. For each finding, fill all required fields per the agent-output schema.

OUTPUT SHAPE — two schemas exist in this plugin; use the right one:

Your output is an **agent-output** document (schema: `${CLAUDE_PLUGIN_ROOT}/skills/review/schemas/agent-output.schema.json`), NOT the cross-skill envelope. Top-level keys of your output file are exactly:

- `agent_id` (required)
- `concern`, `concern_slug` (required — set to the values this prompt was parameterized with)
- `dimension_name`, `dimension_slug`, `dimension_scope` (required — set to the values this prompt was parameterized with)
- `findings` (array — see FINDING SCHEMA below)
- `cross_cutting_observations` (optional array of strings)

The shared handoff contract you may have seen in the skill's pre-fetch context describes the **final envelope** assembled by the main agent AFTER all sub-agents finish. Do NOT emit envelope-level keys — `schema_version`, `source`, `project`, `decomposition`, `issues`, `supplementary`, `applied` — in your output. They are the main agent's job; including them here causes your output to fail agent-output validation and your entire file is dropped from consolidation.

Run `python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py <OUTPUT PATH>` immediately after writing to confirm the shape is correct before finishing.

FINDING SCHEMA — every finding object inside `findings[]` MUST contain exactly these fields. Use these field names verbatim — do NOT invent alternatives like `description`, `details`, `severity`, `id`, etc. (the schema rejects unknown fields):

- `title`: short summary, ≤120 chars
- `impact`: integer 0–100, blast radius if the issue manifests
- `likelihood`: integer 0–100, probability the issue actually occurs in real use
- `effort_to_fix`: integer 0–100, lower = cheaper to fix
- `confidence`: integer 0–100, your certainty this is a real issue with concrete evidence
- `locations`: non-empty array of `{path, line, role?}` objects (see LOCATIONS below)
- `issue`: 1–3 sentence prose description of the problem
- `why_it_matters`: prose grounding the finding in the project's own patterns or stated standards
- `suggested_fix`: prose describing the recommended change

Do NOT drop low-confidence findings. Validators downstream may rescore; the render step segregates low-confidence items into a `needs-review` bucket.

The `agent_output` schema does not include `severity` or `id` fields — do not invent them. The render step assigns both from your numerical scores.

LOCATIONS — every finding requires at least one entry in `locations`:
- Use file:line or file:line-range under `locations[].path` / `locations[].line`.
- For "X is missing" findings, cite the spec/plan/standards file:line where the requirement is stated, with `role: "requirement"`.
- Multiple locations are allowed; mark non-primary entries with `role: "related" | "callsite" | "requirement"`.

HARD EXCLUSIONS — never report:
- Style issues already enforced by linters/formatters
- Missing tests for trivial code (getters/setters/data classes)
- Architecture concerns in `scripts/` or one-off utilities
- Issues already caught by make targets
- Missing docstrings on private functions
- Generic best-practice advice not grounded in a specific code location

PROHIBITED ACTIONS:
- Do NOT modify any source code or tests.
- Do NOT execute the user's program (no `python -c`, no `node`, no `go run`).
- Do NOT install or upgrade packages.
- Do NOT pipe code to a runtime.

OUTPUT PROCEDURE — strict:
1. Construct the full agent_output JSON in your response.
2. Write it to the OUTPUT PATH (single Write call).
3. Invoke the validator: `python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py <OUTPUT PATH>`. `${CLAUDE_PLUGIN_ROOT}` is substituted by Claude Code to the plugin's install path before the command runs. If the call is denied, abort and report the failure rather than retrying with permutations.
4. If the validator exits non-zero, read its error output, repair the JSON, Write again, validate again.
5. **Hard cap: 3 attempts total** (1 initial + 2 retries). If the JSON does not validate after 3 attempts, return a structured failure message in your final response: `{"status": "failure", "reason": "<validator output>"}`. Do not return success without a passing validation.

The agent_output schema lives at `${CLAUDE_PLUGIN_ROOT}/skills/review/schemas/agent-output.schema.json`. Read it directly if you need to confirm field names and value constraints.
```

## Critical Rules

- **NEVER execute anything against the user's code or environment.** Static analysis only. This single rule subsumes:
  - No running the user's program (`python -m <module>`, `node`, `go run`, etc.)
  - No installing or upgrading packages (`pip`, `npm`, `cargo`, etc.)
  - No piping code to a runtime (`echo "..." | python`, `python -c "..."`, equivalents in any language)
  - No writing or running ad-hoc test files to "verify" a finding. The presence of a missing test is itself a finding — file it as one. **Anything that would otherwise need a runtime check is a missing test, not a script you write.**
  - No `make install`, `make build`, `make run`, `make deploy`, or any target that installs or executes the program.
  - The Build & Checks agent is the only agent allowed to run anything (`make` check targets only — `format`, `lint`, `typecheck`, `test`, `coverage`).
- **Writes are restricted by tool boundary, not just intent:**
  - **Concern agents (`general-purpose` subagent_type)** may Write *only* to their pre-assigned absolute path `<pwd>/.tmp-review/raw/<concern_slug>-<dimension_slug>.json` (the main agent substitutes the Pre-Fetch `pwd` value before dispatching). Any other Write — anywhere on disk, inside or outside the project — is a violation and the agent must stop and report.
  - **Validation agents (`feature-dev:code-reviewer` subagent_type)** are structurally read-only — they cannot Write at all.
  - **Main agent** writes only to `./.tmp-review/` and the three output files at the project root (`Findings-review[-<slug>].json|.md|-supplementary.md`). No edits anywhere else. In particular: **never Write, Edit, or `mv` anything into `${CLAUDE_PLUGIN_ROOT}/`** — the plugin tree is read-only from inside a skill run. Do not create ad-hoc helper scripts (`apply_verdicts.py`, `merge.py`, etc.) even in the workspace — Step 7 is explicit in-memory reasoning, not code generation.
- **Bash is restricted by tool boundary too:**
  - **Concern agents:** Bash only to invoke `python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py <their assigned output path>`. No other Bash command is permitted.
  - **Validation agents:** no Bash (structural).
  - **Main agent:** Bash limited to the skill's allowlisted scripts (bootstrap, validators, renderer, pre-fetch helpers).
- **Prefer allowlisted commands** — agents receive the allowlist as context. Stick to pre-approved commands to avoid blocking the review on user approval prompts.
- **All findings need `finding.locations[]` entries** — the schema enforces this; the validator rejects missing locations.
- **Acknowledge strengths** — a good review recognizes what works well; the supplementary file has a Strengths section. Sub-agents may note positive patterns in their `cross_cutting_observations` field if they wish to call them out.
- **Review is observation, not action** — the review identifies findings and gaps for other agents or the user to act on later. If something needs runtime verification, recommend it as a next step in the review.
